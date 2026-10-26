"""The monitoring figures, computed from job rows when asked (as the dashboard's are).

Every function takes the devices a caller may see (``access.devices_for(owner,
'view')``), so a token sees exactly what its owner would. Sections are grouped
queries, not one query per device or group; ``monitoring.snapshots`` caches them.
Field names and meanings are in ``monitoring.catalogue``.
"""

import statistics
from collections import defaultdict
from datetime import datetime, timedelta

from django.conf import settings
from django.db.models import Count, F, Max, OuterRef, Q, QuerySet, Subquery, Sum
from django.utils import timezone
from redis import Redis
from redis.exceptions import RedisError

from backups.freshness import device_freshness
from backups.models import BackupJob
from backups.scheduler import LEASE_KEY
from core.models import Worker
from core.workers import is_online
from devices import lifecycle
from devicevault_protocol import jobs, push
from devicevault_protocol.registration import ROLE_RECEIVER, STATUS_APPROVED, STATUS_PENDING, STATUS_REVOKED
from devicevault_protocol.version import version
from monitoring.catalogue import FAILING, FINISHED_STATES, WINDOWS, code
from push.models import PushRejection
from storage.models import StorageTarget

TICK_KEY = 'dv:scheduler:last_tick'
FAILED = (BackupJob.FAILED, BackupJob.TIMED_OUT)
RUNNING = (BackupJob.COLLECTING, BackupJob.COLLECTED, BackupJob.STORING)
UNGROUPED = 'ungrouped'


def _seconds(epoch: datetime | None) -> int:
    return int(epoch.timestamp()) if epoch else 0


def _ratio(part: int, whole: int) -> float | None:
    return round(100.0 * part / whole, 2) if whole else None


def _reason_q(reason: str) -> Q:
    """Failed jobs with ``reason``; failures recorded before reasons existed count as unknown."""
    failed = Q(state__in=FAILED)
    if reason == jobs.FAILURE_UNKNOWN:
        return failed & (Q(failure_reason=reason) | Q(failure_reason__isnull=True) | Q(failure_reason=''))
    return failed & Q(failure_reason=reason)


# --- outcomes, timing, change and volume ---------------------------------------------------


def _job_aggregates(now: datetime) -> dict:
    """Conditional aggregates over job rows, by catalogue key."""
    out = {}
    for window, seconds in WINDOWS.items():
        since = now - timedelta(seconds=seconds)
        finished = Q(finished_at__gte=since)
        for state in FINISHED_STATES:
            out[f'{state}_{window}'] = Count('id', filter=finished & Q(state=state))
        stored = finished & Q(state=BackupJob.STORED)
        out[f'retried_{window}'] = Count('id', filter=Q(created_at__gte=since, attempts__gt=1))
        out[f'changed_{window}'] = Count('id', filter=stored & Q(changed=True))
        out[f'bytes_stored_{window}'] = Sum('size_bytes', filter=stored, default=0)
        for change in ('added', 'removed', 'modified'):
            out[f'lines_{change}_{window}'] = Sum(f'lines_{change}', filter=stored, default=0)
    for state in FINISHED_STATES:
        out[f'{state}_total'] = Count('id', filter=Q(state=state))
    day = Q(finished_at__gte=now - timedelta(days=1))
    for reason in jobs.FAILURE_REASONS:
        out[f'failures_{reason}_24h'] = Count('id', filter=day & _reason_q(reason))
        out[f'failures_{reason}_total'] = Count('id', filter=_reason_q(reason))
    out['queued'] = Count('id', filter=Q(state=BackupJob.QUEUED))
    out['running'] = Count('id', filter=Q(state__in=RUNNING))
    held = Q(state=BackupJob.STORED, pruned_at__isnull=True, prune_requested_at__isnull=True)
    out['backups_held'] = Count('id', filter=held)
    out['bytes_held'] = Sum('size_bytes', filter=held, default=0)
    return out


def _add_ratios(row: dict) -> dict:
    for window in WINDOWS:
        finished = sum(row[f'{state}_{window}'] for state in FINISHED_STATES)
        row[f'finished_{window}'] = finished
        row[f'success_ratio_{window}'] = _ratio(row[f'stored_{window}'], finished)
        failed = row[f'failed_{window}'] + row[f'timed_out_{window}']
        row[f'failure_ratio_{window}'] = _ratio(failed, finished)
    return row


def _durations(rows: list[tuple]) -> dict:
    """Average, median, p95 and maximum per stage, in seconds, of (collect_ms, store_ms, wait_s, total_s) rows."""
    stages = {'collect': [], 'store': [], 'wait': [], 'total': []}
    for collect_ms, store_ms, wait, total in rows:
        if collect_ms is not None:
            stages['collect'].append(collect_ms / 1000)
        if store_ms is not None:
            stages['store'].append(store_ms / 1000)
        if wait is not None:
            stages['wait'].append(wait)
        if total is not None:
            stages['total'].append(total)
    out = {}
    for stage, values in stages.items():
        values.sort()
        out[f'duration_{stage}_avg'] = round(statistics.fmean(values), 3) if values else None
        out[f'duration_{stage}_p50'] = round(statistics.median(values), 3) if values else None
        out[f'duration_{stage}_p95'] = (
            round(values[min(len(values) - 1, int(0.95 * len(values)))], 3) if values else None
        )
        out[f'duration_{stage}_max'] = round(values[-1], 3) if values else None
    return out


def _freshness_counts(rows: list[dict], now: datetime) -> dict:
    """Device counts and the stalest device, from ``device_states`` rows."""
    active = [row for row in rows if not row['inactive']]
    enabled = [row for row in active if row['enabled']]
    backed_up = [row for row in enabled if row['last_success']]
    out = {
        'devices_total': len(active),
        'devices_enabled': len(enabled),
        'devices_disabled': len(active) - len(enabled),
        'devices_inactive': len(rows) - len(active),
        'devices_never': len(enabled) - len(backed_up),
        'devices_overdue': sum(1 for row in enabled if row['overdue']),
        **{f'devices_failing_{n}': sum(1 for row in enabled if row['failures'] >= n) for n in FAILING},
        'oldest_success_age': 0,
        'oldest_success_device': '',
    }
    if backed_up:
        stalest = min(backed_up, key=lambda row: row['last_success'])
        out['oldest_success_age'] = int((now - stalest['last_success']).total_seconds())
        out['oldest_success_device'] = stalest['name']
    return out


def _consecutive_failures(devices: QuerySet) -> QuerySet:
    """``devices`` annotated with ``last_ok`` and ``failures``: failed jobs since the newest stored one."""
    last_ok = (
        BackupJob.objects.filter(device=OuterRef('pk'), state=BackupJob.STORED)
        .order_by('-finished_at')
        .values('finished_at')[:1]
    )
    since = Q(last_ok__isnull=True) | Q(backup_jobs__finished_at__gt=F('last_ok'))
    return devices.annotate(last_ok=Subquery(last_ok)).annotate(
        failures=Count('backup_jobs', filter=Q(backup_jobs__state__in=FAILED) & since)
    )


def device_states(devices: QuerySet, now: datetime) -> list[dict]:
    """Per device: its group, whether it is enabled and active, last success, overdue and failures in a row."""
    freshness = device_freshness(devices, now)
    rows = _consecutive_failures(devices.order_by()).values(
        'pk', 'name', 'device_group_id', 'enabled', 'inactive_at', 'failures'
    )
    return [
        {
            'id': row['pk'],
            'name': row['name'],
            'group': row['device_group_id'],
            'enabled': row['enabled'],
            'inactive': row['inactive_at'] is not None,
            'last_success': freshness[row['pk']].last_success,
            'overdue': bool(freshness[row['pk']].overdue),
            'failures': row['failures'],
        }
        for row in rows
    ]


def job_sections(devices: QuerySet, now: datetime | None = None) -> tuple[dict, dict]:
    """(estate, {group id or 'ungrouped': figures}) for ``devices``."""
    now = now or timezone.now()
    jobs_of = BackupJob.objects.filter(device__in=devices)
    aggregates = _job_aggregates(now)
    by_group = {
        row.pop('device__device_group_id') or UNGROUPED: row
        for row in jobs_of.order_by().values('device__device_group_id').annotate(**aggregates)
    }
    estate = jobs_of.aggregate(**aggregates)

    day = now - timedelta(days=1)
    timing = jobs_of.filter(finished_at__gte=day).values_list(
        'device__device_group_id', 'state', 'collect_duration_ms', 'store_duration_ms', 'created_at', 'started_at',
        'finished_at',
    )  # fmt: skip
    samples: dict = defaultdict(list)
    for group, state, collect_ms, store_ms, created, started, finished in timing:
        stored = state == BackupJob.STORED
        sample = (
            collect_ms if stored else None,
            store_ms if stored else None,
            (started - created).total_seconds() if started else None,
            (finished - created).total_seconds() if stored else None,
        )
        samples[group or UNGROUPED].append(sample)

    states = device_states(devices, now)
    states_by_group: dict = defaultdict(list)
    for row in states:
        states_by_group[row['group'] or UNGROUPED].append(row)

    groups = {}
    for group in set(by_group) | set(states_by_group):
        row = by_group.get(group) or {key: 0 for key in estate}
        row = _add_ratios({key: value or 0 for key, value in row.items()})
        row.update(_durations(samples.get(group, [])))
        row.update(_freshness_counts(states_by_group.get(group, []), now))
        groups[group] = row
    estate = _add_ratios({key: value or 0 for key, value in estate.items()})
    estate.update(_durations([sample for rows in samples.values() for sample in rows]))
    estate.update(_freshness_counts(states, now))
    return estate, groups


def push_figures(devices: QuerySet, now: datetime | None = None) -> dict:
    """Estate push figures. Refusals have no device, so they are counted for every caller alike."""
    now = now or timezone.now()
    day = now - timedelta(days=1)
    pushed = BackupJob.objects.filter(device__in=devices, trigger=BackupJob.TRIGGER_PUSH, state=BackupJob.STORED)
    refusals = dict(
        PushRejection.objects.filter(at__gte=day).values('reason').annotate(n=Count('id')).values_list('reason', 'n')
    )
    week = now - timedelta(days=7)
    silent = (
        devices.filter(enabled=True, inactive_at__isnull=True)
        .exclude(push_mode=push.PUSH_OFF)
        .exclude(backup_jobs__trigger=BackupJob.TRIGGER_PUSH, backup_jobs__created_at__gte=week)
        .count()
    )
    return {
        'push_accepted_24h': pushed.filter(finished_at__gte=day).count(),
        'push_refused_24h': sum(refusals.values()),
        **{f'push_refused_{reason}_24h': refusals.get(reason, 0) for reason in push.REASONS},
        'push_last_at': _seconds(pushed.aggregate(at=Max('finished_at'))['at']),
        'push_silent_7d': silent,
    }


def self_figures(now: datetime | None = None) -> dict:
    now = now or timezone.now()
    return {
        'version': version(),
        'payload_encryption': int(settings.DEVICEVAULT_PAYLOAD_ENCRYPTION),
        'server_time': _seconds(now),
    }


def summary(devices: QuerySet, now: datetime | None = None) -> dict:
    now = now or timezone.now()
    estate, _ = job_sections(devices, now)
    return {**estate, **push_figures(devices, now), **self_figures(now)}


def device_groups(devices: QuerySet, groups: QuerySet, now: datetime | None = None) -> list[dict]:
    """One entry per visible device group (and ``ungrouped`` when it has devices), for discovery."""
    estate, figures = job_sections(devices, now)
    blank = {key: _blank(key, value) for key, value in estate.items()}
    entries = []
    for group in groups.order_by('name'):
        entries.append({'id': str(group.pk), 'name': group.name, **figures.get(group.pk, blank)})
    if UNGROUPED in figures:
        entries.append({'id': UNGROUPED, 'name': 'Ungrouped', **figures[UNGROUPED]})
    return entries


def _blank(key: str, value):
    """A group with no devices: zero counts, null ratios and durations, empty text."""
    if key.startswith(('success_ratio', 'failure_ratio', 'duration_')):
        return None
    return '' if isinstance(value, str) else 0


# --- platform ------------------------------------------------------------------------------


def _redis() -> Redis:
    return Redis.from_url(settings.DEVICEVAULT_BUS.redis_url, socket_connect_timeout=2, socket_timeout=2)


def note_tick(now: datetime | None = None) -> None:
    """Record that the scheduler leader ran its tick (the platform figures report its age)."""
    try:
        _redis().set(TICK_KEY, int((now or timezone.now()).timestamp()))
    except RedisError:
        pass  # the tick itself went fine; the figure just goes stale


def _status_code(worker: Worker) -> int:
    return code('worker_status', {STATUS_PENDING: 'pending', STATUS_APPROVED: 'approved'}.get(worker.status, 'revoked'))


def workers(now: datetime | None = None) -> list[dict]:
    now = now or timezone.now()
    entries = []
    for worker in Worker.objects.order_by('name'):
        seen = worker.last_seen_at
        entries.append(
            {
                'id': str(worker.pk),
                'name': worker.name,
                'role': worker.role,
                'status_code': _status_code(worker),
                'online': int(is_online(worker, now)),
                'heartbeat_age': int((now - seen).total_seconds()) if seen else -1,
                'pending_age': int((now - worker.registered_at).total_seconds())
                if worker.status == STATUS_PENDING and getattr(worker, 'registered_at', None)
                else 0,
                'version': worker.version,
                'assignment_behind': int(
                    worker.status == STATUS_APPROVED and worker.applied_version < worker.desired_version
                ),
            }
        )
    return entries


def platform(now: datetime | None = None) -> dict:
    now = now or timezone.now()
    rows = workers(now)
    approved = [row for row in rows if row['status_code'] == code('worker_status', 'approved')]
    out = {
        'workers_online': sum(row['online'] for row in approved),
        'workers_offline': sum(1 - row['online'] for row in approved),
        'workers_pending': sum(1 for row in rows if row['status_code'] == code('worker_status', 'pending')),
        'workers_revoked': sum(1 for row in rows if row['status_code'] == code('worker_status', 'revoked')),
        'workers_behind': sum(row['assignment_behind'] for row in approved),
    }
    redis = _redis()
    ttl_ms = redis.pttl(LEASE_KEY)
    tick = redis.get(TICK_KEY)
    out['scheduler_leader'] = int(ttl_ms > 0)
    out['scheduler_lease_ttl'] = max(0, ttl_ms // 1000) if ttl_ms > 0 else 0
    out['scheduler_tick_age'] = int(now.timestamp() - int(tick)) if tick else -1
    return out


def storage_targets(now: datetime | None = None) -> list[dict]:
    now = now or timezone.now()
    day = now - timedelta(days=1)
    held = Q(jobs__state=BackupJob.STORED, jobs__pruned_at__isnull=True, jobs__prune_requested_at__isnull=True)
    stored_day = Q(jobs__state=BackupJob.STORED, jobs__finished_at__gte=day)
    targets = StorageTarget.objects.order_by('name').annotate(
        last_stored=Max('jobs__finished_at', filter=Q(jobs__state=BackupJob.STORED)),
        failures=Count('jobs', filter=Q(jobs__state__in=FAILED, jobs__finished_at__gte=day)
                       & Q(jobs__failure_reason__in=[jobs.FAILURE_STORAGE, jobs.FAILURE_INTEGRITY])),
        held=Count('jobs', filter=held),
        held_bytes=Sum('jobs__size_bytes', filter=held, default=0),
        day_bytes=Sum('jobs__size_bytes', filter=stored_day, default=0),
    )  # fmt: skip
    entries = []
    for target in targets.prefetch_related('workers'):
        online = [w for w in target.workers.all() if w.status == STATUS_APPROVED and is_online(w, now)]
        entries.append(
            {
                'id': str(target.pk),
                'name': target.name,
                'driver': target.driver,
                'workers_online': len(online),
                'last_stored_at': _seconds(target.last_stored),
                'storage_failures_24h': target.failures,
                'backups_held': target.held,
                'bytes_held': target.held_bytes,
                'bytes_stored_24h': target.day_bytes,
            }
        )
    return entries


def receivers(now: datetime | None = None) -> list[dict]:
    now = now or timezone.now()
    day = now - timedelta(days=1)
    entries = []
    for worker in Worker.objects.filter(role=ROLE_RECEIVER).exclude(status=STATUS_REVOKED).order_by('name'):
        pushed = BackupJob.objects.filter(trigger=BackupJob.TRIGGER_PUSH, collector=worker.name)
        entries.append(
            {
                'id': str(worker.pk),
                'name': worker.name,
                'online': int(is_online(worker, now)),
                'accepted_24h': pushed.filter(created_at__gte=day).count(),
                'refused_24h': PushRejection.objects.filter(worker=worker, at__gte=day).count(),
                'last_push_at': _seconds(pushed.aggregate(at=Max('created_at'))['at']),
            }
        )
    return entries


# --- devices -------------------------------------------------------------------------------


def _status(latest: dict | None) -> str:
    if latest is None:
        return 'never'
    if latest['state'] in BackupJob.ACTIVE_STATES:
        return 'running'
    return latest['state']


def device_rows(devices: QuerySet, now: datetime | None = None) -> tuple[dict[int, dict], dict[str, int]]:
    """Per-device figures for the relay snapshot, and the index from active address to device id."""
    now = now or timezone.now()
    week = now - timedelta(days=7)
    newest = BackupJob.objects.filter(device=OuterRef('pk')).order_by('-created_at')
    held = Q(backup_jobs__state=BackupJob.STORED, backup_jobs__pruned_at__isnull=True)
    week_finished = Q(backup_jobs__finished_at__gte=week, backup_jobs__state__in=FINISHED_STATES)
    base = _consecutive_failures(devices.order_by().select_related('device_group')).annotate(
        latest_id=Subquery(newest.values('pk')[:1]),
        latest_ok_id=Subquery(newest.filter(state=BackupJob.STORED).order_by('-finished_at').values('pk')[:1]),
        last_failure=Max('backup_jobs__finished_at', filter=Q(backup_jobs__state__in=FAILED)),
        last_push=Max('backup_jobs__finished_at', filter=Q(backup_jobs__trigger=BackupJob.TRIGGER_PUSH,
                                                           backup_jobs__state=BackupJob.STORED)),
        held=Count('backup_jobs', filter=held),
        pinned_count=Count('backup_jobs', filter=held & Q(backup_jobs__pinned=True)),
        week_finished=Count('backup_jobs', filter=week_finished),
        week_stored=Count('backup_jobs', filter=week_finished & Q(backup_jobs__state=BackupJob.STORED)),
    )  # fmt: skip
    devices_list = list(base)
    job_ids = {d.latest_id for d in devices_list} | {d.latest_ok_id for d in devices_list}
    jobs_by_id = {
        row['pk']: row
        for row in BackupJob.objects.filter(pk__in=[pk for pk in job_ids if pk]).values(
            'pk', 'state', 'failure_reason', 'created_at', 'started_at', 'finished_at', 'collect_duration_ms',
            'store_duration_ms', 'size_bytes', 'changed', 'lines_added', 'lines_removed', 'lines_modified',
        )
    }  # fmt: skip
    freshness = device_freshness(devices, now)
    inactive = [d.pk for d in devices_list if d.inactive_at is not None]
    deletable = set(
        lifecycle.filter_lifecycle(lifecycle.with_lifecycle(devices.filter(pk__in=inactive)), lifecycle.DELETABLE)
        .values_list('pk', flat=True)
    ) if inactive else set()  # fmt: skip

    rows, by_ip = {}, {}
    for device in devices_list:
        latest = jobs_by_id.get(device.latest_id)
        ok = jobs_by_id.get(device.latest_ok_id)
        fresh = freshness[device.pk]
        status = _status(latest)
        reason = (latest.get('failure_reason') or jobs.FAILURE_UNKNOWN) if status in FAILED else 'none'
        attempt = latest and (latest['finished_at'] or latest['started_at'] or latest['created_at'])
        state = 'active' if device.inactive_at is None else ('deletable' if device.pk in deletable else 'inactive')
        rows[device.pk] = {
            'id': str(device.pk),
            'name': device.name,
            'group': device.device_group.name if device.device_group else '',
            'ip': device.ip_address,
            'enabled': int(device.enabled),
            'lifecycle_code': code('lifecycle', state),
            'status_code': code('job_status', status),
            'last_attempt_at': _seconds(attempt),
            'last_success_at': _seconds(fresh.last_success),
            'last_failure_at': _seconds(device.last_failure),
            'failure_reason_code': code('failure_reason', reason),
            'consecutive_failures': device.failures,
            'expected_interval': int(fresh.expected_interval.total_seconds()) if fresh.expected_interval else 0,
            'next_due_at': _seconds(fresh.next_due_at),
            'overdue': int(bool(fresh.overdue)),
            'last_collect_duration': ok['collect_duration_ms'] / 1000 if ok and ok['collect_duration_ms'] else 0,
            'last_store_duration': ok['store_duration_ms'] / 1000 if ok and ok['store_duration_ms'] else 0,
            'last_duration': (ok['finished_at'] - ok['created_at']).total_seconds() if ok and ok['finished_at'] else 0,
            'last_size': ok['size_bytes'] or 0 if ok else 0,
            'last_changed': int(bool(ok and ok['changed'])),
            'last_lines_added': ok['lines_added'] or 0 if ok else 0,
            'last_lines_removed': ok['lines_removed'] or 0 if ok else 0,
            'last_lines_modified': ok['lines_modified'] or 0 if ok else 0,
            'backups_held': device.held,
            'pinned': device.pinned_count,
            'push_mode': device.push_mode,
            'last_push_at': _seconds(device.last_push),
            'success_ratio_7d': _ratio(device.week_stored, device.week_finished),
        }
        if device.inactive_at is None:
            by_ip[device.ip_address] = device.pk
    return rows, by_ip
