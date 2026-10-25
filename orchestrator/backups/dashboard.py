"""Dashboard cards: one endpoint each, computed on request from job rows (ARCHITECTURE.md section 7.3).

Every card covers only the devices the user can view (``access.devices_for(user, 'view')``),
except push refusals, which belong to no device group and are for global administrators.
Daily series use calendar days in the display time zone, oldest first, with every day present.
"""

from datetime import date, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Max, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework import decorators, response, status
from rest_framework.permissions import IsAuthenticated

from accounts import access
from accounts.access import IsGlobalAdmin
from backups.models import BackupJob
from core.timezone_utils import get_day_bounds_local, get_timezone_name, local_now
from devices.models import Device
from push.models import PushRejection

FAILED_STATES = (BackupJob.FAILED, BackupJob.TIMED_OUT)
ACTIVITY_WINDOWS = {'1h': timedelta(hours=1), '24h': timedelta(hours=24), '7d': timedelta(days=7)}
PERIODS = (7, 14, 30, 90)
DEFAULT_PERIOD = 30
FAILING_LIMIT = 10
FAILING_MAX = 50
ERROR_CHARS = 200
TOP_SOURCES = 10
STALE_AFTER = (('older_24h', timedelta(hours=24)), ('older_7d', timedelta(days=7)))

DURATION = ExpressionWrapper(F('finished_at') - F('created_at'), output_field=DurationField())


class BadParameter(ValueError):
    pass


def _period(request) -> int:
    raw = request.query_params.get('days', DEFAULT_PERIOD)
    try:
        days = int(raw)
    except TypeError, ValueError:
        days = 0
    if days not in PERIODS:
        raise BadParameter(f'days must be one of {", ".join(map(str, PERIODS))}.')
    return days


def _days(days: int) -> list[date]:
    today = local_now().date()
    return [today - timedelta(days=offset) for offset in range(days - 1, -1, -1)]


def _local_day(field: str) -> TruncDate:
    return TruncDate(field, tzinfo=ZoneInfo(settings.DEVICEVAULT_DISPLAY_TIMEZONE))


def _seconds(value: timedelta | None) -> float | None:
    return round(value.total_seconds(), 1) if value is not None else None


def _visible_jobs(user):
    return BackupJob.objects.filter(device__in=access.devices_for(user, 'view'))


def card(*permissions):
    """A GET endpoint taking ``days`` where it needs one; a bad parameter is a 400."""

    def wrap(view):
        def handler(request):
            try:
                return response.Response(view(request))
            except BadParameter as exc:
                return response.Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        handler.__name__ = handler.__qualname__ = view.__name__
        handler.__doc__ = view.__doc__
        return decorators.api_view(['GET'])(decorators.permission_classes(permissions)(handler))

    return wrap


@card(IsAuthenticated)
def summary(request):
    """Today's tiles: devices by type and the last 24 hours of backups."""
    since = timezone.now() - timedelta(hours=24)
    devices = access.devices_for(request.user, 'view').filter(inactive_at__isnull=True)
    jobs = _visible_jobs(request.user)
    recent = jobs.filter(finished_at__gte=since)
    by_type = devices.values('device_type__name', 'device_type__icon').annotate(count=Count('id'))
    average = recent.filter(state=BackupJob.STORED).annotate(d=DURATION).aggregate(avg=Avg('d'))['avg']
    with_status = devices.exclude(last_backup_status='')
    healthy = with_status.filter(last_backup_status='success').count()
    return {
        'devices_by_type': [
            {'name': row['device_type__name'] or '', 'icon': row['device_type__icon'], 'count': row['count']}
            for row in by_type
        ],
        'stored_24h': recent.filter(state=BackupJob.STORED).count(),
        'failed_24h': recent.filter(state__in=FAILED_STATES).count(),
        'in_progress': jobs.filter(state__in=BackupJob.ACTIVE_STATES).count(),
        'avg_duration_s': _seconds(average) or 0.0,
        # Devices whose latest finished backup succeeded, of those backed up at all.
        'device_success_rate': round(healthy / with_status.count() * 100, 1) if with_status.exists() else None,
        'timezone': get_timezone_name(),
    }


@card(IsAuthenticated)
def activity(request):
    """The latest jobs started in ``window`` (1h, 24h or 7d), newest first, at most 200."""
    window = ACTIVITY_WINDOWS.get(request.query_params.get('window', '1h'), ACTIVITY_WINDOWS['1h'])
    jobs = (
        _visible_jobs(request.user)
        .filter(created_at__gte=timezone.now() - window)
        .select_related('device')
        .order_by('-created_at')[:200]
    )
    return [
        {
            'id': str(job.id),
            'device_id': job.device_id,
            'device_name': job.device.name,
            'state': job.state,
            'trigger': job.trigger,
            'created_at': job.created_at,
            'finished_at': job.finished_at,
            'duration_ms': job.duration_ms,
            'error': job.error,
            'has_log': bool(job.log),
        }
        for job in jobs
    ]


@card(IsAuthenticated)
def trend(request):
    """Per day: stored and failed backups, success rate, durations and how many changed."""
    days = _days(_period(request))
    start, _ = get_day_bounds_local(days[0])
    rows = (
        _visible_jobs(request.user)
        .filter(finished_at__gte=start, state__in=(BackupJob.STORED, *FAILED_STATES))
        .annotate(day=_local_day('finished_at'), took=DURATION)
        .values('day')
        .annotate(
            stored=Count('id', filter=Q(state=BackupJob.STORED)),
            failed=Count('id', filter=Q(state__in=FAILED_STATES)),
            changed=Count('id', filter=Q(state=BackupJob.STORED, changed=True)),
            avg_duration=Avg('took', filter=Q(state=BackupJob.STORED)),
            max_duration=Max('took', filter=Q(state=BackupJob.STORED)),
            avg_collect_ms=Avg('collect_duration_ms', filter=Q(state=BackupJob.STORED)),
        )
    )
    by_day = {row['day']: row for row in rows}
    series = []
    for day in days:
        row = by_day.get(day, {})
        stored, failed = row.get('stored', 0), row.get('failed', 0)
        collect = row.get('avg_collect_ms')
        series.append(
            {
                'date': day.isoformat(),
                'stored': stored,
                'failed': failed,
                'rate': round(stored / (stored + failed) * 100, 1) if stored + failed else None,
                'changed': row.get('changed', 0),
                'avg_duration_s': _seconds(row.get('avg_duration')),
                'max_duration_s': _seconds(row.get('max_duration')),
                'avg_collect_s': round(collect / 1000, 1) if collect is not None else None,
            }
        )
    return {'days': series, 'timezone': get_timezone_name()}


def _stalest_first(device: Device):
    # Never backed up sorts before any time.
    return (device.last_success is not None, device.last_success or 0)


@card(IsAuthenticated)
def freshness(request):
    """Per device group: how old each enabled, active device's latest successful backup is."""
    now = timezone.now()
    devices = (
        access.devices_for(request.user, 'view')
        .filter(enabled=True, inactive_at__isnull=True)
        .select_related('device_group')
        .annotate(last_success=Max('backup_jobs__finished_at', filter=Q(backup_jobs__state=BackupJob.STORED)))
    )
    groups: dict[int | None, list[Device]] = {}
    for device in devices:
        groups.setdefault(device.device_group_id, []).append(device)
    rows = []
    for group_id, members in groups.items():
        members.sort(key=_stalest_first)
        stalest = members[0]
        backed_up = [d.last_success for d in members if d.last_success is not None]
        row = {
            'device_group': group_id,
            'device_group_name': stalest.device_group.name if stalest.device_group else '',
            'devices': len(members),
            'never': len(members) - len(backed_up),
            **{key: sum(1 for at in backed_up if now - at > age) for key, age in STALE_AFTER},
            'stalest': {'id': stalest.pk, 'name': stalest.name, 'last_success': stalest.last_success},
        }
        rows.append(row)
    rows.sort(key=lambda row: (row['stalest']['last_success'] is not None, row['stalest']['last_success'] or 0))
    return rows


@card(IsAuthenticated)
def failing(request):
    """The devices with the most failed or timed-out backups in the period."""
    days = _days(_period(request))
    try:
        limit = min(max(int(request.query_params.get('limit', FAILING_LIMIT)), 1), FAILING_MAX)
    except ValueError:
        raise BadParameter('limit must be a number.') from None
    start, _ = get_day_bounds_local(days[0])
    jobs = _visible_jobs(request.user)
    top = (
        jobs.filter(finished_at__gte=start, state__in=FAILED_STATES)
        .values('device', 'device__name')
        .annotate(failed=Count('id'), last_failed=Max('finished_at'))
        .order_by('-failed', '-last_failed')[:limit]
    )
    rows = []
    for entry in top:
        history = jobs.filter(device=entry['device'])
        latest_failure = history.filter(state__in=FAILED_STATES).order_by('-finished_at').first()
        newest = history.filter(state__in=BackupJob.TERMINAL_STATES).order_by('-finished_at').first()
        rows.append(
            {
                'device': entry['device'],
                'device_name': entry['device__name'],
                'failed': entry['failed'],
                'stored': history.filter(finished_at__gte=start, state=BackupJob.STORED).count(),
                'last_failed': entry['last_failed'],
                'last_success': history.filter(state=BackupJob.STORED).aggregate(at=Max('finished_at'))['at'],
                'error': latest_failure.error[:ERROR_CHARS] if latest_failure else '',
                'recovered': newest is not None and newest.state == BackupJob.STORED,
            }
        )
    return rows


@card(IsAuthenticated)
def storage(request):
    """Per storage target: the backups it holds (not deleted by retention) and their logical size."""
    days = _days(_period(request))
    start, _ = get_day_bounds_local(days[0])
    rows = (
        _visible_jobs(request.user)
        .filter(state=BackupJob.STORED, prune_requested_at__isnull=True, pruned_at__isnull=True)
        .values('storage_target', 'storage_target__name', 'storage_target__driver')
        .annotate(
            backups=Count('id'),
            total_bytes=Sum('size_bytes'),
            added_bytes=Sum('size_bytes', filter=Q(finished_at__gte=start)),
            added_backups=Count('id', filter=Q(finished_at__gte=start)),
        )
        .order_by('-total_bytes', 'storage_target__name')
    )
    return [
        {
            'storage_target': str(row['storage_target']),
            'name': row['storage_target__name'],
            'driver': row['storage_target__driver'],
            'backups': row['backups'],
            'size_bytes': row['total_bytes'] or 0,
            'added_backups': row['added_backups'],
            'added_bytes': row['added_bytes'] or 0,
        }
        for row in rows
    ]


@card(IsGlobalAdmin)
def push_refusals(request):
    """Pushes the receivers refused in the period: per day, by reason, and the top sources."""
    days = _days(_period(request))
    start, _ = get_day_bounds_local(days[0])
    refusals = PushRejection.objects.filter(at__gte=start)
    per_day = dict(
        refusals.annotate(day=_local_day('at')).values('day').annotate(n=Count('id')).values_list('day', 'n')
    )
    sources = []
    for entry in refusals.values('source_ip').annotate(count=Count('id')).order_by('-count', 'source_ip')[:TOP_SOURCES]:
        latest = refusals.filter(source_ip=entry['source_ip']).select_related('worker').order_by('-at').first()
        sources.append(
            {
                'source_ip': entry['source_ip'],
                'count': entry['count'],
                'last_at': latest.at,
                'last_reason': latest.reason,
                'receiver': latest.worker.name,
            }
        )
    return {
        'days': [{'date': day.isoformat(), 'count': per_day.get(day, 0)} for day in days],
        'by_reason': list(refusals.values('reason').annotate(count=Count('id')).order_by('-count', 'reason')),
        'sources': sources,
    }
