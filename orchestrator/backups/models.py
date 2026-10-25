# SPDX-License-Identifier: GPL-3.0-or-later
"""Backup jobs: one row per backup attempt of a device, from request to storage."""

import uuid

from django.contrib.auth.models import User
from django.db import models

LABEL_MAX = 64
NOTE_MAX = 2000


class BackupJob(models.Model):
    """A backup of one device, tracked through collection and storage.

    States: queued -> collecting -> collected -> stored, or failed / timed_out
    at any point. ``stored`` is the only successful outcome.
    """

    QUEUED = 'queued'
    COLLECTING = 'collecting'
    COLLECTED = 'collected'
    STORING = 'storing'
    STORED = 'stored'
    FAILED = 'failed'
    TIMED_OUT = 'timed_out'

    STATE_CHOICES = [
        (QUEUED, 'Queued'),
        (COLLECTING, 'Collecting'),
        (COLLECTED, 'Collected'),
        (STORING, 'Storing'),
        (STORED, 'Stored'),
        (FAILED, 'Failed'),
        (TIMED_OUT, 'Timed out'),
    ]
    ACTIVE_STATES = (QUEUED, COLLECTING, COLLECTED, STORING)
    TERMINAL_STATES = (STORED, FAILED, TIMED_OUT)

    TRIGGER_MANUAL = 'manual'
    TRIGGER_SCHEDULE = 'schedule'
    TRIGGER_PUSH = 'push'
    TRIGGER_CHOICES = [
        (TRIGGER_MANUAL, 'Manual'),
        (TRIGGER_SCHEDULE, 'Schedule'),
        (TRIGGER_PUSH, 'Pushed by the device'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device = models.ForeignKey('devices.Device', on_delete=models.CASCADE, related_name='backup_jobs')
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default=QUEUED, db_index=True)
    trigger = models.CharField(max_length=16, choices=TRIGGER_CHOICES, default=TRIGGER_MANUAL)
    requested_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    schedule = models.ForeignKey(
        'policies.BackupSchedule', null=True, blank=True, on_delete=models.SET_NULL, related_name='jobs'
    )

    driver = models.CharField(max_length=128, help_text='Collector driver used ("push:<protocol>" for pushes)')
    source_filename = models.CharField(max_length=255, blank=True, help_text='Name the device pushed the file as')
    is_binary = models.BooleanField(default=False)
    collector = models.CharField(max_length=255, blank=True, help_text='Worker that collected (or received) it')
    storage_worker = models.CharField(max_length=255, blank=True, help_text='Worker that stored it')

    # Protected: deleting a target would make its backups unreadable.
    storage_target = models.ForeignKey('storage.StorageTarget', on_delete=models.PROTECT, related_name='jobs')
    storage_driver = models.CharField(max_length=64, blank=True, help_text='Storage driver of the target when queued')
    storage_ref = models.CharField(max_length=512, blank=True)

    collected_sha256 = models.CharField(max_length=64, blank=True)
    stored_sha256 = models.CharField(max_length=64, blank=True)
    size_bytes = models.BigIntegerField(null=True, blank=True)
    encrypted = models.BooleanField(default=False)

    # Retention (backups.retention). A pinned backup is never deleted by it. Once a
    # deletion is requested the content is treated as gone; ``pruned_at`` is set when
    # the storage worker confirms it. The job row stays as the record.
    pinned = models.BooleanField(default=False, help_text='Exempt from retention')
    pinned_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    pinned_at = models.DateTimeField(null=True, blank=True)
    prune_requested_at = models.DateTimeField(null=True, blank=True)
    pruned_at = models.DateTimeField(null=True, blank=True)
    # What people say about it ("pre-upgrade 17.9", "approved baseline"); see backups.api.
    label = models.CharField(max_length=LABEL_MAX, blank=True)
    note = models.TextField(blank=True)
    annotated_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    annotated_at = models.DateTimeField(null=True, blank=True)

    # Change summary (backups.changes), filled in shortly after the job is stored: how it
    # differs from the device's previous backup, ignoring the driver's volatile lines.
    # ``changed`` is None until summarised (or if it could not be); line counts are None
    # for binary backups. The first backup of a device has no ``compared_to`` and counts
    # every line as added. A modified line (one replaced by another) is counted only as
    # modified, as the compare view shows it.
    compared_to = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    changed = models.BooleanField(null=True, blank=True, db_index=True)
    lines_added = models.PositiveIntegerField(null=True, blank=True)
    lines_removed = models.PositiveIntegerField(null=True, blank=True)
    lines_modified = models.PositiveIntegerField(null=True, blank=True)
    summary_error = models.CharField(max_length=255, blank=True, help_text='Why no change summary could be made')

    attempts = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True)
    log = models.JSONField(default=list, blank=True, help_text='Structured log entries from every stage')

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    collected_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True, db_index=True)
    collect_duration_ms = models.PositiveIntegerField(null=True, blank=True)
    store_duration_ms = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        # (state, finished_at): the dashboard's daily trend, failing devices and storage figures.
        indexes = [models.Index(fields=['device', '-created_at']), models.Index(fields=['state', 'finished_at'])]

    def __str__(self):
        return f'{self.device} {self.created_at:%Y-%m-%d %H:%M} [{self.state}]'

    @property
    def is_active(self) -> bool:
        return self.state in self.ACTIVE_STATES

    @property
    def succeeded(self) -> bool:
        return self.state == self.STORED

    @property
    def pruned(self) -> bool:
        """Deleted (or being deleted) by retention, so its content can no longer be read."""
        return bool(self.prune_requested_at or self.pruned_at)

    @property
    def duration_ms(self) -> int | None:
        """Request to completion."""
        if not self.finished_at:
            return None
        return int((self.finished_at - self.created_at).total_seconds() * 1000)
