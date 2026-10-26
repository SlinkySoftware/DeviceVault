"""Every monitoring metric, declared once.

The JSON endpoints (``monitoring.metrics``), the Prometheus renderer
(``monitoring.prometheus``) and the Zabbix template generator all read this list,
and a test fails if an endpoint returns a key it lacks or the reverse.

A metric's ``key`` is a flat field of one section entry (``$.success_ratio_24h``
for Zabbix JSONPath). ``scope`` says which entries carry it: the estate summary,
one entry per device group, worker, storage target or receiver, or one device.
Numbers are never null except ratios and durations with nothing to measure;
codes (``*_code``) carry a value map, since Zabbix maps numbers, not text.
"""

from dataclasses import dataclass, field

from devicevault_protocol import jobs, push

ESTATE = 'estate'
GROUP = 'group'
DEVICE = 'device'
WORKER = 'worker'
TARGET = 'target'
RECEIVER = 'receiver'
PLATFORM = 'platform'  # estate-wide platform health, in the summary when the caller may see it
SCOPES = (ESTATE, GROUP, DEVICE, WORKER, TARGET, RECEIVER, PLATFORM)

GAUGE = 'gauge'
COUNTER = 'counter'

WINDOWS = {'1h': 3600, '24h': 86400, '7d': 7 * 86400}
FINISHED_STATES = ('stored', 'failed', 'timed_out')
STAGES = {'collect': 'collection', 'store': 'storage', 'wait': 'queue wait', 'total': 'request to stored'}
STATS = {'avg': 'average', 'p50': 'median', 'p95': '95th percentile', 'max': 'maximum'}
QUANTILES = {'avg': 'avg', 'p50': '0.5', 'p95': '0.95', 'max': 'max'}
FAILING = (1, 3, 5)

# Value maps: code -> label. Codes are stable; new ones are only ever appended.
VALUE_MAPS = {
    'job_status': {0: 'never', 1: 'stored', 2: 'failed', 3: 'timed_out', 4: 'running'},
    'failure_reason': {0: 'none', **{n: reason for n, reason in enumerate(jobs.FAILURE_REASONS, start=1)}},
    'lifecycle': {0: 'active', 1: 'inactive', 2: 'deletable'},
    'worker_status': {0: 'pending', 1: 'approved', 2: 'revoked'},
    'boolean': {0: 'no', 1: 'yes'},
}


def code(value_map: str, label: str) -> int:
    """The code of ``label`` in ``value_map``."""
    for number, name in VALUE_MAPS[value_map].items():
        if name == label:
            return number
    raise KeyError(f'{label!r} is not in value map {value_map!r}')


@dataclass(frozen=True)
class Metric:
    key: str
    name: str
    scope: str
    kind: str = GAUGE
    unit: str = ''  # '', 's', 'B', '%', 'unixtime'
    value_type: str = 'float'  # 'float', 'int' or 'text' (Zabbix value types)
    description: str = ''
    value_map: str | None = None
    # Prometheus series name and labels; None leaves the metric out of Prometheus.
    prometheus: str | None = None
    labels: dict[str, str] = field(default_factory=dict)


def _job_metrics(scope: str) -> list[Metric]:
    """Outcomes, timing, freshness, change and volume: the estate summary and each device group."""
    where = 'the estate' if scope == ESTATE else 'the device group'
    out = []
    for window in WINDOWS:
        for state in FINISHED_STATES:
            out.append(
                Metric(
                    f'{state}_{window}',
                    f'Backups {state.replace("_", " ")} ({window})',
                    scope,
                    value_type='int',
                    description=f'Jobs of {where} that finished {state.replace("_", " ")} in the last {window}',
                    prometheus='devicevault_backups_finished',
                    labels={'state': state, 'window': window},
                )
            )
        out += [
            Metric(
                f'finished_{window}',
                f'Backups finished ({window})',
                scope,
                value_type='int',
                description=f'Jobs of {where} that finished in the last {window}, whatever the outcome',
            ),
            Metric(
                f'success_ratio_{window}',
                f'Success ratio ({window})',
                scope,
                unit='%',
                description=f'Stored as a share of finished jobs in the last {window}; null with none finished',
                prometheus='devicevault_backup_success_ratio',
                labels={'window': window},
            ),
            Metric(
                f'failure_ratio_{window}',
                f'Failure ratio ({window})',
                scope,
                unit='%',
                description=f'Failed or timed out as a share of finished jobs in the last {window}',
                prometheus='devicevault_backup_failure_ratio',
                labels={'window': window},
            ),
            Metric(
                f'retried_{window}',
                f'Backups retried ({window})',
                scope,
                value_type='int',
                description=f'Jobs created in the last {window} that needed more than one attempt',
                prometheus='devicevault_backups_retried',
                labels={'window': window},
            ),
            Metric(
                f'changed_{window}',
                f'Backups with changes ({window})',
                scope,
                value_type='int',
                description=f'Stored backups in the last {window} that differ from the one before',
                prometheus='devicevault_backups_changed',
                labels={'window': window},
            ),
            Metric(
                f'bytes_stored_{window}',
                f'Bytes stored ({window})',
                scope,
                unit='B',
                value_type='int',
                description=f'Size of the backups stored in the last {window}',
                prometheus='devicevault_bytes_stored',
                labels={'window': window},
            ),
        ]
        for change in ('added', 'removed', 'modified'):
            out.append(
                Metric(
                    f'lines_{change}_{window}',
                    f'Lines {change} ({window})',
                    scope,
                    value_type='int',
                    description=f'Configuration lines {change} by the backups stored in the last {window}',
                    prometheus='devicevault_config_lines_changed',
                    labels={'change': change, 'window': window},
                )
            )
    for state in FINISHED_STATES:
        out.append(
            Metric(
                f'{state}_total',
                f'Backups {state.replace("_", " ")} (all time)',
                scope,
                kind=COUNTER,
                value_type='int',
                description=f'Every job of {where} that finished {state.replace("_", " ")}, while its row exists',
                prometheus='devicevault_backups_finished_total',
                labels={'state': state},
            )
        )
    for reason in jobs.FAILURE_REASONS:
        out += [
            Metric(
                f'failures_{reason}_24h',
                f'Failures: {reason} (24h)',
                scope,
                value_type='int',
                description=f'Jobs that failed in the last 24h for reason "{reason}"',
                prometheus='devicevault_backup_failures',
                labels={'reason': reason, 'window': '24h'},
            ),
            Metric(
                f'failures_{reason}_total',
                f'Failures: {reason} (all time)',
                scope,
                kind=COUNTER,
                value_type='int',
                description=f'Every failed job with reason "{reason}" (older failures without a reason count as unknown)',
                prometheus='devicevault_backup_failures_total',
                labels={'reason': reason},
            ),
        ]
    out += [
        Metric(
            'queued',
            'Backups queued',
            scope,
            value_type='int',
            description='Jobs waiting for a collector now',
            prometheus='devicevault_backups_active',
            labels={'phase': 'queued'},
        ),
        Metric(
            'running',
            'Backups running',
            scope,
            value_type='int',
            description='Jobs being collected or stored now',
            prometheus='devicevault_backups_active',
            labels={'phase': 'running'},
        ),
    ]
    for stage, stage_name in STAGES.items():
        for stat, stat_name in STATS.items():
            out.append(
                Metric(
                    f'duration_{stage}_{stat}',
                    f'Duration of {stage_name}, {stat_name} (24h)',
                    scope,
                    unit='s',
                    description=f'The {stat_name} {stage_name} time of the jobs that finished in the last 24h',
                    prometheus='devicevault_backup_duration_seconds',
                    labels={'stage': stage, 'quantile': QUANTILES[stat], 'window': '24h'},
                )
            )
    devices = [
        ('devices_total', 'Devices', 'Active devices', 'active'),
        ('devices_enabled', 'Devices enabled', 'Active devices that are not paused', 'enabled'),
        ('devices_disabled', 'Devices disabled', 'Active devices that are paused', 'disabled'),
        ('devices_inactive', 'Devices inactive', 'Devices marked inactive (retired, held)', 'inactive'),
        ('devices_never', 'Devices never backed up', 'Active, enabled devices with no stored backup', 'never'),
        (
            'devices_overdue',
            'Devices overdue',
            'Active, enabled devices whose last success is older than their schedule allows',
            'overdue',
        ),
    ]
    for key, name, description, state in devices:
        out.append(
            Metric(
                key, name, scope, value_type='int', description=description,
                prometheus='devicevault_devices', labels={'state': state},
            )
        )  # fmt: skip
    for count in FAILING:
        out.append(
            Metric(
                f'devices_failing_{count}',
                f'Devices failing {count}+ times in a row',
                scope,
                value_type='int',
                description=f'Active, enabled devices whose last {count} or more finished jobs all failed',
                prometheus='devicevault_devices_failing',
                labels={'consecutive': str(count)},
            )
        )
    out += [
        Metric(
            'oldest_success_age',
            'Oldest last success, age',
            scope,
            unit='s',
            value_type='int',
            description='Seconds since the stalest active, enabled device last backed up (0 with none backed up)',
            prometheus='devicevault_oldest_success_age_seconds',
        ),
        Metric(
            'oldest_success_device',
            'Oldest last success, device',
            scope,
            value_type='text',
            description='Name of that device',
        ),
        Metric(
            'backups_held',
            'Backups held',
            scope,
            value_type='int',
            description='Stored backups not pruned by retention',
            prometheus='devicevault_backups_held',
        ),
        Metric(
            'bytes_held',
            'Bytes held',
            scope,
            unit='B',
            value_type='int',
            description='Size of those backups (as the collectors reported it)',
            prometheus='devicevault_bytes_held',
        ),
    ]
    return out


def _identity(scope: str) -> list[Metric]:
    return [
        Metric('id', 'Id', scope, value_type='text', description='Identifier, used by low-level discovery'),
        Metric('name', 'Name', scope, value_type='text', description='Name'),
    ]


ESTATE_EXTRA = [
    Metric(
        'push_accepted_24h',
        'Pushes accepted (24h)',
        ESTATE,
        value_type='int',
        description='Files devices pushed in the last 24h that became backups',
        prometheus='devicevault_pushes_accepted',
        labels={'window': '24h'},
    ),
    Metric(
        'push_refused_24h',
        'Pushes refused (24h)',
        ESTATE,
        value_type='int',
        description='Refused pushes in the last 24h (receivers rate-limit reports, so a lower bound)',
        prometheus='devicevault_pushes_refused',
        labels={'reason': 'any', 'window': '24h'},
    ),
    *[
        Metric(
            f'push_refused_{reason}_24h',
            f'Pushes refused: {reason} (24h)',
            ESTATE,
            value_type='int',
            description=f'Pushes refused in the last 24h for reason "{reason}"',
            prometheus='devicevault_pushes_refused',
            labels={'reason': reason, 'window': '24h'},
        )
        for reason in push.REASONS
    ],
    Metric(
        'push_last_at',
        'Last push',
        ESTATE,
        unit='unixtime',
        value_type='int',
        description='When a device last pushed a file that was accepted (0 if never)',
        prometheus='devicevault_push_last_timestamp_seconds',
    ),
    Metric(
        'push_silent_7d',
        'Push devices silent (7d)',
        ESTATE,
        value_type='int',
        description='Active, enabled push devices with no accepted push in the last 7 days',
        prometheus='devicevault_push_devices_silent',
        labels={'window': '7d'},
    ),
    Metric('version', 'DeviceVault version', ESTATE, value_type='text', description='The orchestrator version'),
    Metric(
        'payload_encryption',
        'Payload encryption',
        ESTATE,
        value_type='int',
        value_map='boolean',
        description='Whether backups and secrets sent to workers are encrypted (DV_PAYLOAD_ENCRYPTION)',
        prometheus='devicevault_payload_encryption',
    ),
    Metric(
        'server_time',
        'Server time',
        ESTATE,
        unit='unixtime',
        value_type='int',
        description='The orchestrator clock, to compare with the monitoring server (clock skew)',
    ),
    Metric(
        'computed_at',
        'Figures computed at',
        ESTATE,
        unit='unixtime',
        value_type='int',
        description='When these figures were computed (they are cached briefly)',
    ),
    Metric(
        'computed_age',
        'Figures age',
        ESTATE,
        unit='s',
        value_type='int',
        description='Seconds since these figures were computed',
        prometheus='devicevault_metrics_age_seconds',
    ),
]

PLATFORM_METRICS = [
    *[
        Metric(
            f'workers_{state}',
            f'Workers {label}',
            PLATFORM,
            value_type='int',
            description=description,
            prometheus='devicevault_workers',
            labels={'state': state},
        )
        for state, label, description in [
            ('online', 'online', 'Approved workers that sent a heartbeat recently'),
            ('offline', 'offline', 'Approved workers with no recent heartbeat'),
            ('pending', 'pending approval', 'Workers waiting for approval'),
            ('revoked', 'revoked', 'Revoked workers'),
        ]
    ],
    Metric(
        'workers_behind',
        'Workers behind on their assignment',
        PLATFORM,
        value_type='int',
        description='Approved workers whose applied assignment version is older than the current one',
        prometheus='devicevault_workers_assignment_behind',
    ),
    Metric(
        'scheduler_leader',
        'Scheduler has a leader',
        PLATFORM,
        value_type='int',
        value_map='boolean',
        description='Whether a scheduler node holds the lease',
        prometheus='devicevault_scheduler_leader',
    ),
    Metric(
        'scheduler_lease_ttl',
        'Scheduler lease remaining',
        PLATFORM,
        unit='s',
        value_type='int',
        description="Seconds left on the leader's lease (0 without a leader)",
        prometheus='devicevault_scheduler_lease_seconds',
    ),
    Metric(
        'scheduler_tick_age',
        'Scheduler last tick, age',
        PLATFORM,
        unit='s',
        value_type='int',
        description='Seconds since the leader last ran its tick (-1 if it never has)',
        prometheus='devicevault_scheduler_tick_age_seconds',
    ),
]

WORKER_METRICS = [
    *_identity(WORKER),
    Metric('role', 'Role', WORKER, value_type='text', description='collector, storage or receiver'),
    Metric(
        'status_code',
        'Status',
        WORKER,
        value_type='int',
        value_map='worker_status',
        description='Approval status',
        prometheus='devicevault_worker_status',
    ),
    Metric(
        'online',
        'Online',
        WORKER,
        value_type='int',
        value_map='boolean',
        description='Sent a heartbeat recently',
        prometheus='devicevault_worker_online',
    ),
    Metric(
        'heartbeat_age',
        'Heartbeat age',
        WORKER,
        unit='s',
        value_type='int',
        description='Seconds since the last heartbeat (-1 if never)',
        prometheus='devicevault_worker_heartbeat_age_seconds',
    ),
    Metric(
        'pending_age',
        'Pending approval for',
        WORKER,
        unit='s',
        value_type='int',
        description='Seconds since a pending worker registered (0 once decided)',
        prometheus='devicevault_worker_pending_seconds',
    ),
    Metric('version', 'Version', WORKER, value_type='text', description='The DeviceVault version it runs'),
    Metric(
        'assignment_behind',
        'Assignment behind',
        WORKER,
        value_type='int',
        value_map='boolean',
        description='Applied assignment version is older than the current one',
        prometheus='devicevault_worker_assignment_behind',
    ),
]

TARGET_METRICS = [
    *_identity(TARGET),
    Metric('driver', 'Driver', TARGET, value_type='text', description='Storage driver'),
    Metric(
        'workers_online',
        'Workers online',
        TARGET,
        value_type='int',
        description='Approved storage workers serving it that are online',
        prometheus='devicevault_storage_target_workers_online',
    ),
    Metric(
        'last_stored_at',
        'Last stored',
        TARGET,
        unit='unixtime',
        value_type='int',
        description='When a backup was last stored there (0 if never)',
        prometheus='devicevault_storage_target_last_stored_timestamp_seconds',
    ),
    Metric(
        'storage_failures_24h',
        'Storage failures (24h)',
        TARGET,
        value_type='int',
        description='Jobs for it that failed at the storage step in the last 24h',
        prometheus='devicevault_storage_target_failures',
        labels={'window': '24h'},
    ),
    Metric(
        'backups_held',
        'Backups held',
        TARGET,
        value_type='int',
        description='Stored backups not pruned by retention',
        prometheus='devicevault_storage_target_backups_held',
    ),
    Metric(
        'bytes_held',
        'Bytes held',
        TARGET,
        unit='B',
        value_type='int',
        description='Size of those backups',
        prometheus='devicevault_storage_target_bytes_held',
    ),
    Metric(
        'bytes_stored_24h',
        'Bytes stored (24h)',
        TARGET,
        unit='B',
        value_type='int',
        description='Size of the backups stored there in the last 24h',
        prometheus='devicevault_storage_target_bytes_stored',
        labels={'window': '24h'},
    ),
]

RECEIVER_METRICS = [
    *_identity(RECEIVER),
    Metric(
        'online',
        'Online',
        RECEIVER,
        value_type='int',
        value_map='boolean',
        description='Sent a heartbeat recently',
        prometheus='devicevault_receiver_online',
    ),
    Metric(
        'accepted_24h',
        'Pushes accepted (24h)',
        RECEIVER,
        value_type='int',
        description='Files it accepted in the last 24h',
        prometheus='devicevault_receiver_pushes_accepted',
        labels={'window': '24h'},
    ),
    Metric(
        'refused_24h',
        'Pushes refused (24h)',
        RECEIVER,
        value_type='int',
        description='Pushes it refused in the last 24h (a lower bound)',
        prometheus='devicevault_receiver_pushes_refused',
        labels={'window': '24h'},
    ),
    Metric(
        'last_push_at',
        'Last push',
        RECEIVER,
        unit='unixtime',
        value_type='int',
        description='When it last accepted a file (0 if never)',
        prometheus='devicevault_receiver_last_push_timestamp_seconds',
    ),
]

DEVICE_METRICS = [
    Metric('found', 'Found in DeviceVault', DEVICE, value_type='int', value_map='boolean',
           description='1 when the address or id matches a device the token may see'),
    *_identity(DEVICE),
    Metric('group', 'Device group', DEVICE, value_type='text', description='Device group name (empty if none)'),
    Metric('ip', 'Address', DEVICE, value_type='text', description='The address DeviceVault backs up'),
    Metric('enabled', 'Enabled', DEVICE, value_type='int', value_map='boolean', description='Not paused'),
    Metric('lifecycle_code', 'Lifecycle', DEVICE, value_type='int', value_map='lifecycle',
           description='Active, inactive (retired, held) or deletable'),
    Metric('status_code', 'Backup status', DEVICE, value_type='int', value_map='job_status',
           description='The latest job: stored, failed, timed out, running, or never backed up'),
    Metric('last_attempt_at', 'Last attempt', DEVICE, unit='unixtime', value_type='int',
           description='When the latest job finished, or started if it is still running (0 if never)'),
    Metric('last_success_at', 'Last successful backup', DEVICE, unit='unixtime', value_type='int',
           description='When the newest stored backup finished (0 if never)'),
    Metric('last_success_age', 'Last successful backup, age', DEVICE, unit='s', value_type='int',
           description='Seconds since then, at answer time (0 if never)'),
    Metric('last_failure_at', 'Last failure', DEVICE, unit='unixtime', value_type='int',
           description='When a job last failed or timed out (0 if never)'),
    Metric('failure_reason_code', 'Failure reason', DEVICE, value_type='int', value_map='failure_reason',
           description='Why the latest job failed (none when it did not)'),
    Metric('consecutive_failures', 'Consecutive failures', DEVICE, value_type='int',
           description='Finished jobs that failed since the last stored one'),
    Metric('expected_interval', 'Expected interval', DEVICE, unit='s', value_type='int',
           description="The longest gap between the schedule's runs (0 without a schedule)"),
    Metric('next_due_at', 'Next backup due by', DEVICE, unit='unixtime', value_type='int',
           description='When a successful backup is due before the device counts as overdue (0 without a schedule)'),
    Metric('overdue', 'Overdue', DEVICE, value_type='int', value_map='boolean',
           description='Its last success is older than its schedule allows'),
    Metric('last_collect_duration', 'Last collection time', DEVICE, unit='s',
           description='Collection time of the newest stored backup'),
    Metric('last_store_duration', 'Last storage time', DEVICE, unit='s',
           description='Storage time of the newest stored backup'),
    Metric('last_duration', 'Last backup duration', DEVICE, unit='s',
           description='Request-to-stored time of the newest stored backup'),
    Metric('last_size', 'Last backup size', DEVICE, unit='B', value_type='int',
           description='Size of the newest stored backup'),
    Metric('last_changed', 'Last backup changed', DEVICE, value_type='int', value_map='boolean',
           description='The newest stored backup differs from the one before'),
    Metric('last_lines_added', 'Lines added', DEVICE, value_type='int', description='By the newest stored backup'),
    Metric('last_lines_removed', 'Lines removed', DEVICE, value_type='int', description='By the newest stored backup'),
    Metric('last_lines_modified', 'Lines modified', DEVICE, value_type='int',
           description='By the newest stored backup'),
    Metric('backups_held', 'Backups held', DEVICE, value_type='int', description='Stored backups not pruned'),
    Metric('pinned', 'Pinned backups', DEVICE, value_type='int', description='Backups pinned against retention'),
    Metric('push_mode', 'Push mode', DEVICE, value_type='text', description='off, ssh or tftp'),
    Metric('last_push_at', 'Last push', DEVICE, unit='unixtime', value_type='int',
           description='When the device last pushed a file that was accepted (0 if never)'),
    Metric('success_ratio_7d', 'Success ratio (7d)', DEVICE, unit='%',
           description='Stored as a share of finished jobs in the last 7 days; null with none finished'),
    Metric('published_at', 'Data published at', DEVICE, value_type='text',
           description='When the orchestrator published the snapshot this answer comes from'),
    Metric('published_age', 'Data age', DEVICE, unit='s', value_type='int',
           description='Seconds since that snapshot was published'),
]  # fmt: skip

CATALOGUE: list[Metric] = [
    *_job_metrics(ESTATE),
    *ESTATE_EXTRA,
    *PLATFORM_METRICS,
    *_identity(GROUP),
    *_job_metrics(GROUP),
    *WORKER_METRICS,
    *TARGET_METRICS,
    *RECEIVER_METRICS,
    *DEVICE_METRICS,
]


def metrics(scope: str) -> list[Metric]:
    return [metric for metric in CATALOGUE if metric.scope == scope]


def keys(scope: str) -> list[str]:
    return [metric.key for metric in metrics(scope)]
