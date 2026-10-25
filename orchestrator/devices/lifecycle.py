"""Retiring and deleting devices (ARCHITECTURE.md 7.5).

A device is removed in two steps. ``deactivate`` marks it inactive: it is never
backed up again, and its backups are held for its retention policy's
``inactive_keep_days`` before retention deletes them all (``backups.retention``).
Once nothing retention could delete is left, the device is *deletable* and
``delete`` removes it with its job rows. A global administrator can ``purge`` an
inactive device to end the hold at once, pins included.

Backups on targets whose driver keeps everything (git) never block deletion; they
stay in that target's history.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from django.db import transaction
from django.db.models import Count, Max, Min, Q, QuerySet, Sum
from django.utils import timezone

from backups.models import BackupJob
from backups.retention import keeping_drivers, purge_jobs, request_deletion
from devices.models import Device

ACTIVE = 'active'
INACTIVE = 'inactive'
DELETABLE = 'deletable'


class LifecycleError(Exception):
    """The device is not in a state that allows this. ``conflict`` answers 409 rather than 400."""

    def __init__(self, message: str, *, conflict: bool = False):
        super().__init__(message)
        self.conflict = conflict


def _held(keeping: set[str]) -> Q:
    """Backups retention could still delete: stored, not pruned, on a target that deletes.

    Their backups on targets that keep everything (git) never hold a device.
    """
    return (
        Q(backup_jobs__state=BackupJob.STORED, backup_jobs__prune_requested_at__isnull=True)
        & Q(backup_jobs__pruned_at__isnull=True)
        & ~Q(backup_jobs__storage_ref='')
        & ~Q(backup_jobs__storage_target__driver__in=keeping)
    )


def with_lifecycle(devices: QuerySet) -> QuerySet:
    """Annotate ``devices`` with the counts ``Lifecycle`` needs, in one query."""
    held = _held(keeping_drivers())
    return devices.annotate(
        held_backups=Count('backup_jobs', filter=held, distinct=True),
        held_bytes=Sum('backup_jobs__size_bytes', filter=held, default=0),
        pinned_backups=Count('backup_jobs', filter=held & Q(backup_jobs__pinned=True), distinct=True),
        deleting_backups=Count(
            'backup_jobs',
            filter=Q(backup_jobs__prune_requested_at__isnull=False, backup_jobs__pruned_at__isnull=True),
            distinct=True,
        ),
        stored_backups=Count('backup_jobs', filter=Q(backup_jobs__state=BackupJob.STORED), distinct=True),
    )


def filter_lifecycle(devices: QuerySet, state: str) -> QuerySet:
    """Devices of ``with_lifecycle(devices)`` in ``state``."""
    if state == ACTIVE:
        return devices.filter(inactive_at__isnull=True)
    gone = Q(held_backups=0, deleting_backups=0)
    if state == DELETABLE:
        return devices.filter(gone, inactive_at__isnull=False)
    return devices.filter(~gone, inactive_at__isnull=False)


@dataclass
class Lifecycle:
    state: str
    held_backups: int
    held_bytes: int
    pinned_backups: int
    deleting_backups: int
    stored_backups: int
    # The end of the hold; None while active, purged, or kept with no time limit.
    held_until: datetime | None

    @property
    def can_delete(self) -> bool:
        """Deletable, or never stored a backup (added by mistake, never backed up)."""
        if self.held_backups or self.deleting_backups:
            return False
        return self.state == DELETABLE or self.stored_backups == 0

    def refusal(self) -> str:
        """Why the device cannot be deleted yet."""
        if self.deleting_backups:
            return f'{self.deleting_backups} backup deletion(s) are still waiting for the storage worker.'
        if self.state == ACTIVE:
            return 'Mark the device inactive first.'
        if self.pinned_backups:
            return f'It is held by {self.pinned_backups} pinned backup(s). Unpin them, or purge the device.'
        if self.held_until is not None:
            return f'Its backups are held until {self.held_until:%Y-%m-%d %H:%M} UTC by its retention policy.'
        return f'Its retention policy keeps its {self.held_backups} backup(s) with no time limit.'


def hold_end(device: Device) -> datetime | None:
    """When an inactive device's hold ends (None: no end, or not inactive, or purged)."""
    policy = device.retention_policy
    if device.inactive_at is None or device.purge_requested_at or policy is None or policy.inactive_keep_days is None:
        return None
    return device.inactive_at + timedelta(days=policy.inactive_keep_days)


def lifecycle(device: Device) -> Lifecycle:
    """The device's state; uses ``with_lifecycle`` annotations when present."""
    if not hasattr(device, 'held_backups'):
        device = with_lifecycle(Device.objects.filter(pk=device.pk)).select_related('retention_policy').get()
    if device.inactive_at is None:
        state = ACTIVE
    elif device.held_backups or device.deleting_backups:
        state = INACTIVE
    else:
        state = DELETABLE
    return Lifecycle(
        state=state,
        held_backups=device.held_backups,
        held_bytes=device.held_bytes,
        pinned_backups=device.pinned_backups,
        deleting_backups=device.deleting_backups,
        stored_backups=device.stored_backups,
        held_until=hold_end(device),
    )


def _locked(device: Device) -> Device:
    return Device.objects.select_for_update(of=('self',)).select_related('retention_policy').get(pk=device.pk)


def deactivate(device: Device, user, reason: str = '') -> Device:
    """Mark ``device`` inactive. A job already running finishes; nothing new starts."""
    from search.models import SearchDocument

    with transaction.atomic():
        device = _locked(device)
        if device.inactive_at is not None:
            raise LifecycleError('The device is already inactive.')
        device.inactive_at, device.inactive_by, device.inactive_reason = timezone.now(), user, reason
        device.save()  # push.signals re-sends receiver assignments if it pushed
        # Search shows current configurations, which a retired device no longer has.
        SearchDocument.objects.filter(device=device).delete()
    return device


def reactivate(device: Device) -> Device:
    """Put an inactive device back in service. Backups already deleted stay deleted."""
    with transaction.atomic():
        device = _locked(device)
        if device.inactive_at is None:
            raise LifecycleError('The device is already active.')
        taken = Device.objects.filter(ip_address=device.ip_address, inactive_at__isnull=True).first()
        if taken is not None:
            raise LifecycleError(f'Device "{taken.name}" now uses the address {device.ip_address}.')
        device.inactive_at, device.inactive_by, device.inactive_reason = None, None, ''
        device.purge_requested_at, device.purge_requested_by = None, None
        device.save()
    return device


@dataclass
class Purge:
    device: Device
    requested: list[BackupJob]
    unpinned: list[dict[str, Any]]


def purge(device: Device, user) -> Purge:
    """End an inactive device's hold now: unpin its backups and ask for all of them to be deleted.

    Backups that cannot be sent now (no worker serves their target) are sent by a
    later retention pass (``backups.retention.apply_purges``).
    """
    now = timezone.now()
    with transaction.atomic():
        device = _locked(device)
        if device.inactive_at is None:
            raise LifecycleError('Mark the device inactive before purging it.')
        device.purge_requested_at, device.purge_requested_by = now, user
        device.save(update_fields=['purge_requested_at', 'purge_requested_by'])
        pinned = (
            BackupJob.objects.select_for_update(of=('self',))
            .select_related('pinned_by')
            .filter(device=device, pinned=True)
        )
        unpinned = [
            {'job': str(job.pk), 'label': job.label, 'pinned_by': job.pinned_by.username if job.pinned_by else None}
            for job in pinned
        ]
        BackupJob.objects.filter(device=device, pinned=True).update(pinned=False, pinned_by=None, pinned_at=None)
        requested = request_deletion(purge_jobs(device), now)
    return Purge(device=device, requested=requested, unpinned=unpinned)


def delete(device: Device) -> dict[str, Any]:
    """Delete a deletable device (or one that never stored a backup) with its job rows.

    Returns a snapshot for the audit log, since the row is gone afterwards.
    """
    with transaction.atomic():
        device = _locked(device)
        state = lifecycle(device)
        if not state.can_delete:
            raise LifecycleError(state.refusal(), conflict=True)
        jobs = device.backup_jobs.aggregate(
            count=Count('pk'),
            first=Min('created_at', filter=Q(state=BackupJob.STORED)),
            last=Max('created_at', filter=Q(state=BackupJob.STORED)),
        )
        kept = sorted(
            set(
                device.backup_jobs.filter(
                    state=BackupJob.STORED, pruned_at__isnull=True, prune_requested_at__isnull=True
                )
                .exclude(storage_ref='')
                .values_list('storage_target__name', flat=True)
            )
        )
        snapshot = {
            'device': device.pk,
            'device_name': device.name,
            'address': device.ip_address,
            'device_group': device.device_group.name if device.device_group else None,
            'driver': device.backup_method,
            'jobs': jobs['count'],
            'first_backup': jobs['first'].isoformat() if jobs['first'] else None,
            'last_backup': jobs['last'].isoformat() if jobs['last'] else None,
            'targets_keeping_content': kept,
        }
        device.delete()
    return snapshot
