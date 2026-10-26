"""The Zabbix templates, generated from the metric catalogue (``monitoring.catalogue``).

Two templates, exported for Zabbix 6.0 and 7.0 LTS (``render(version)``):

- ``DeviceVault by HTTP``, for one host standing for DeviceVault. HTTP agent items poll
  ``summary/``, ``device-groups/``, ``workers/``, ``storage-targets/`` and ``receivers/``;
  every value is a dependent item, and dependent low-level discovery rules turn the lists
  into per-group, per-worker, per-target and per-receiver item and trigger prototypes.
- ``DeviceVault Device by HTTP``, linked to the device hosts Zabbix already has. One HTTP
  agent item asks a receiver relay (or the orchestrator) for ``device/?ip={HOST.IP}``.

The content is built once (``_Template``) and written by a small emitter per version, which
differ in the export ``version``, template groups and dashboard widgets. UUIDs are derived
from stable names, so regenerating changes nothing that did not change. ``{$DV.URL}`` and
``{$DV.TOKEN}`` are deliberately not template macros: a template macro would shadow the
global macro the deployment guide sets them as.

``deploy/zabbix/devicevault_zabbix_<version>.yaml`` hold the output (``make zabbix-template``),
and a test fails when they differ from it.
"""

import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from devicevault_protocol import jobs
from monitoring import catalogue as cat
from monitoring.catalogue import VALUE_MAPS, Metric, code

VERSIONS = ('6.0', '7.0')
HOST_TEMPLATE = 'DeviceVault by HTTP'
DEVICE_TEMPLATE = 'DeviceVault Device by HTTP'
TEMPLATE_GROUP = 'Templates/Applications'
API_PATH = '/api/monitoring/'

_NAMESPACE = uuid.UUID('9b6d3c1e-58a4-4f0e-b1d7-2f4c8e6a0d35')

VALUEMAP_NAMES = {
    'job_status': 'DeviceVault job status',
    'failure_reason': 'DeviceVault failure reason',
    'lifecycle': 'DeviceVault lifecycle',
    'worker_status': 'DeviceVault worker status',
    'boolean': 'DeviceVault yes/no',
}

# A value that is not there (a platform key without the platform scope, a device that is not
# found) is discarded rather than turning the item unsupported; so is a JSON null (a ratio or
# duration with nothing to measure), which JSONPath returns as ``null`` or an empty string.
NULL = '^(null)?$'
# Text and value-mapped items rarely change, so unchanged values are kept only hourly, except
# those a trigger reads over a time window (which needs a value in every poll).
HEARTBEAT = '1h'
WINDOWED = {'assignment_behind'}
TIMEOUT = '15s'
COLOURS = ('199C0D', 'F63100', '2774A4', 'F7941D', 'FC6EA3', '6C59DC', 'C7A72D', 'BA2A5D', '0080FF', '808080')

ESTATE = 'all'  # the ``group`` tag of triggers that are not about one device group


def _uuid(*parts: str) -> str:
    """A UUID that only changes when ``parts`` do (Zabbix accepts only version 4 UUIDs)."""
    return uuid.UUID(bytes=uuid.uuid5(_NAMESPACE, '\x1f'.join(parts)).bytes, version=4).hex


def default_path(version: str) -> Path:
    return Path(__file__).resolve().parents[2] / 'deploy' / 'zabbix' / f'devicevault_zabbix_{version}.yaml'


# --- discovery -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Discovery:
    scope: str
    slug: str
    title: str
    label: str
    path: str


DISCOVERIES = (
    Discovery(cat.GROUP, 'group', 'Device groups', 'Group', 'device-groups/'),
    Discovery(cat.WORKER, 'worker', 'Workers', 'Worker', 'workers/'),
    Discovery(cat.TARGET, 'target', 'Storage targets', 'Storage target', 'storage-targets/'),
    Discovery(cat.RECEIVER, 'receiver', 'Receivers', 'Receiver', 'receivers/'),
)
# Identity fields of discovered entries travel as LLD macros, not as items.
LLD_MACROS = {'id': '{#ID}', 'name': '{#NAME}'}


def master_key(discovery: Discovery) -> str:
    return f'dv.{discovery.slug}.get'


def estate_key(key: str) -> str:
    return f'dv.{key}'


def prototype_key(discovery: Discovery, key: str) -> str:
    return f'dv.{discovery.slug}.{key}[{{#ID}}]'


def device_key(key: str) -> str:
    return f'dv.device.{key}'


SUMMARY_KEY = 'dv.summary.get'
STATUS_KEY = 'dv.http.status'
DEVICE_MASTER_KEY = 'dv.device.get'
DEVICE_ERROR_KEY = 'dv.device.error'


# --- content -------------------------------------------------------------------------------


@dataclass
class Trigger:
    name: str
    expression: str
    recovery: str
    priority: str
    description: str
    component: str
    scope: str
    group: str = ESTATE
    depends: list[Trigger] = field(default_factory=list)
    opdata: str = ''

    def reference(self) -> dict:
        return {'name': self.name, 'expression': self.expression, 'recovery_expression': self.recovery}


@dataclass
class Graph:
    name: str
    keys: list[str]
    stacked: bool = False


@dataclass
class Rule:
    """A dependent low-level discovery rule and its prototypes."""

    discovery: Discovery
    items: list[dict] = field(default_factory=list)
    triggers: list[Trigger] = field(default_factory=list)
    graphs: list[Graph] = field(default_factory=list)


@dataclass
class _Template:
    name: str
    description: str
    items: list[dict] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    triggers: list[Trigger] = field(default_factory=list)
    graphs: list[Graph] = field(default_factory=list)
    macros: list[dict] = field(default_factory=list)
    dashboard: list[tuple[str, str]] = field(default_factory=list)  # (graph or prototype, name)

    def ref(self, key: str) -> str:
        return f'/{self.name}/{key}'

    def valuemaps(self) -> list[str]:
        used = {item['valuemap']['name'] for item in self.items if 'valuemap' in item}
        used |= {item['valuemap']['name'] for rule in self.rules for item in rule.items if 'valuemap' in item}
        return [name for value_map, name in VALUEMAP_NAMES.items() if name in used]


def _value_type(metric: Metric) -> str:
    if metric.value_type == 'text':
        return 'CHAR'
    if metric.value_type == 'float' or metric.unit == 's':  # ages may be -1 (never)
        return 'FLOAT'
    return 'UNSIGNED'


def _component(metric: Metric) -> str:
    key = metric.key
    for prefix, component in [
        ('duration_', 'timing'),
        ('failures_', 'failures'),
        ('devices_', 'freshness'),
        ('oldest_', 'freshness'),
        ('push_', 'push'),
        ('lines_', 'changes'),
        ('changed_', 'changes'),
        ('bytes_', 'volume'),
        ('backups_held', 'volume'),
        ('workers_', 'workers'),
        ('scheduler_', 'scheduler'),
    ]:
        if key.startswith(prefix):
            return component
    if metric.scope == cat.ESTATE and key in ('version', 'payload_encryption', 'server_time', 'computed_at',
                                              'computed_age'):  # fmt: skip
        return 'system'
    return 'backups'


def _tags(**tags: str) -> list[dict]:
    return [{'tag': tag, 'value': value} for tag, value in tags.items()]


def _dependent(template: str, metric: Metric, key: str, name: str, master: str, path: str, tags: list[dict]) -> dict:
    item = {
        'uuid': _uuid(template, 'item', key),
        'name': name,
        'type': 'DEPENDENT',
        'key': key,
        'delay': '0',
        'value_type': _value_type(metric),
    }
    if metric.value_type == 'text':
        item['trends'] = '0'
    if metric.unit:
        item['units'] = metric.unit
    if metric.description:
        item['description'] = metric.description
    if metric.value_map:
        item['valuemap'] = {'name': VALUEMAP_NAMES[metric.value_map]}
    steps = [{'type': 'JSONPATH', 'parameters': [path], 'error_handler': 'DISCARD_VALUE'}]
    if metric.value_type == 'float':
        steps.append({'type': 'NOT_MATCHES_REGEX', 'parameters': [NULL], 'error_handler': 'DISCARD_VALUE'})
    if metric.value_type == 'text' or (metric.value_map and metric.key not in WINDOWED):
        steps.append({'type': 'DISCARD_UNCHANGED_HEARTBEAT', 'parameters': [HEARTBEAT]})
    item['preprocessing'] = steps
    item['master_item'] = {'key': master}
    item['tags'] = tags
    return item


def _http(template: str, key: str, name: str, url: str, description: str, delay: str, **extra) -> dict:
    item = {
        'uuid': _uuid(template, 'item', key),
        'name': name,
        'type': 'HTTP_AGENT',
        'key': key,
        'delay': delay,
        'history': '0',
        'trends': '0',
        'value_type': 'TEXT',
        'description': description,
        'timeout': TIMEOUT,
        'url': url,
        'headers': [{'name': 'Authorization', 'value': 'Bearer {$DV.TOKEN}'}],
        'tags': _tags(component='raw'),
    }
    item.update(extra)
    return item


def _macro(macro: str, value: str, description: str) -> dict:
    out = {'macro': macro}
    if value:
        out['value'] = value
    out['description'] = description
    return out


# --- DeviceVault by HTTP -------------------------------------------------------------------


HOST_DESCRIPTION = """\
Backup health of a DeviceVault installation, polled from its read-only monitoring API.

Link it to one host standing for DeviceVault, monitored by the Zabbix server or a proxy that can reach the web tier.
Set {$DV.URL} (the web address, without /api) and {$DV.TOKEN} (a service account's token with the monitoring scope,
plus monitoring_platform for workers, the scheduler, storage targets and receivers) as global macros, or on the host.

Generated by DeviceVault from its metric catalogue; see DEPLOYMENT.md, section Monitoring."""

HOST_MACROS = [
    _macro('{$DV.INTERVAL}', '1m', 'How often the monitoring endpoints are polled.'),
    _macro('{$DV.NODATA}', '5m', 'No answer from the monitoring API for this long raises the unreachable trigger.'),
    _macro('{$DV.SUCCESS.MIN}', '95', 'Lowest acceptable share of backups stored over 24h, in percent.'),
    _macro('{$DV.STALE.MAX}', '2d', 'Longest acceptable age of the oldest last successful backup in a device group.'),
    _macro(
        '{$DV.FAIL.CONSEC}', '3', 'Consecutive failures that count a device as failing (rounded down to 1, 3 or 5).'
    ),
    _macro('{$DV.DURATION.MAX}', '10m', 'Longest acceptable 95th percentile request-to-stored time over 24h.'),
    _macro('{$DV.WORKER.HEARTBEAT.MAX}', '3m', "Longest acceptable gap between an approved worker's heartbeats."),
    _macro('{$DV.PENDING.MAX}', '1h', 'Longest a worker may wait for approval before it is reported.'),
    _macro(
        '{$DV.SKEW.MAX}', '60', 'Largest acceptable difference between the DeviceVault and Zabbix clocks, in seconds.'
    ),
    _macro('{$DV.PUSH.REFUSED.MAX}', '10', 'More refused pushes than this within an hour raise a trigger.'),
]


def _failing(template: _Template, key) -> tuple[str, str]:
    """``{$DV.FAIL.CONSEC}``+ failing devices, from the counts the catalogue has (1+, 3+, 5+)."""
    bounds = list(cat.FAILING) + [None]
    fire, clear = [], []
    for low, high in zip(bounds, bounds[1:], strict=False):
        cond = f'{{$DV.FAIL.CONSEC}}>={low}' if low != bounds[0] else ''
        if high is not None:
            cond = f'{cond} and {{$DV.FAIL.CONSEC}}<{high}' if cond else f'{{$DV.FAIL.CONSEC}}<{high}'
        last = f'last({template.ref(key(f"devices_failing_{low}"))})'
        fire.append(f'({cond} and {last}>0)')
        clear.append(f'({cond} and {last}=0)')
    return ' or '.join(fire), ' or '.join(clear)


def _ratio_trigger(t: _Template, key, where: str, group: str, depends: list[Trigger]) -> Trigger:
    ratio, finished = t.ref(key('success_ratio_24h')), t.ref(key('finished_24h'))
    return Trigger(
        f'DeviceVault: {where}success ratio below {{$DV.SUCCESS.MIN}}% (24h)',
        f'last({ratio})<{{$DV.SUCCESS.MIN}} and last({finished})>0',
        f'last({ratio})>={{$DV.SUCCESS.MIN}} or last({finished})=0',
        'WARNING',
        'Fewer backups than {$DV.SUCCESS.MIN}% of those that finished in the last 24h were stored.',
        'backups',
        'notice',
        group,
        depends,
        opdata='Success ratio: {ITEM.LASTVALUE1}',
    )


def _host_template() -> _Template:
    t = _Template(HOST_TEMPLATE, HOST_DESCRIPTION, macros=HOST_MACROS)
    name = t.name
    url = f'{{$DV.URL}}{API_PATH}'

    t.items.append(
        _http(
            name, SUMMARY_KEY, 'DeviceVault: Get summary', f'{url}summary/',
            'Estate outcomes, timing, freshness, change, volume, push and self, and platform health with that scope.',
            '{$DV.INTERVAL}',
        )
    )  # fmt: skip
    t.items.append(
        {
            'uuid': _uuid(name, 'item', STATUS_KEY),
            'name': 'DeviceVault: API status',
            'type': 'HTTP_AGENT',
            'key': STATUS_KEY,
            'delay': '{$DV.INTERVAL}',
            'description': 'The HTTP status the summary endpoint answers with (200 when the token is accepted).',
            'timeout': TIMEOUT,
            'url': f'{url}summary/',
            'status_codes': '',
            'headers': [{'name': 'Authorization', 'value': 'Bearer {$DV.TOKEN}'}],
            'retrieve_mode': 'HEADERS',
            'preprocessing': [{'type': 'REGEX', 'parameters': ['^HTTP\\/[\\d.]+\\s+(\\d+)', '\\1']}],
            'tags': _tags(component='api'),
        }
    )
    for discovery in DISCOVERIES:
        t.items.append(
            _http(
                name, master_key(discovery), f'DeviceVault: Get {discovery.title.lower()}', f'{url}{discovery.path}',
                f'The {discovery.title.lower()} list ({discovery.path}), read by discovery.', '{$DV.INTERVAL}',
            )
        )  # fmt: skip

    for metric in cat.metrics(cat.ESTATE) + cat.metrics(cat.PLATFORM):
        component = 'platform' if metric.scope == cat.PLATFORM else _component(metric)
        t.items.append(
            _dependent(
                name, metric, estate_key(metric.key), f'DeviceVault: {metric.name}', SUMMARY_KEY,
                f'$.{metric.key}', _tags(component=component),
            )
        )  # fmt: skip

    ref = t.ref
    endpoint = Trigger(
        'DeviceVault: monitoring API unreachable or refusing',
        f'last({ref(STATUS_KEY)})<>200 or nodata({ref(STATUS_KEY)},{{$DV.NODATA}})=1',
        f'last({ref(STATUS_KEY)})=200 and nodata({ref(STATUS_KEY)},{{$DV.NODATA}})=0',
        'HIGH',
        'The summary endpoint did not answer for {$DV.NODATA}, or answered with an error (401 or 403: the token is '
        'unknown, revoked, expired, out of its networks or lacks the monitoring scope; 5xx: DeviceVault is failing).',
        'api',
        'availability',
        opdata='HTTP status: {ITEM.LASTVALUE1}',
    )
    stale = Trigger(
        'DeviceVault: monitoring figures are stale',
        f'last({ref(estate_key("computed_age"))})>3*{{$DV.INTERVAL}} or nodata({ref(estate_key("server_time"))},{{$DV.NODATA}})=1',
        f'last({ref(estate_key("computed_age"))})<=3*{{$DV.INTERVAL}} and nodata({ref(estate_key("server_time"))},{{$DV.NODATA}})=0',
        'WARNING',
        'The figures are older than three poll intervals, or none arrived for {$DV.NODATA}.',
        'api',
        'availability',
        depends=[endpoint],
    )  # fmt: skip
    base = [endpoint, stale]
    estate = lambda key: estate_key(key)  # noqa: E731
    leader = Trigger(
        'DeviceVault: scheduler has no leader',
        f'last({ref(estate("scheduler_leader"))})=0',
        f'last({ref(estate("scheduler_leader"))})=1',
        'HIGH',
        'No scheduler node holds the lease, so no scheduled backup starts.',
        'scheduler',
        'availability',
        depends=base,
    )
    t.triggers += [
        endpoint,
        stale,
        _ratio_trigger(t, estate, '', ESTATE, base),
        Trigger(
            'DeviceVault: devices never backed up',
            f'last({ref(estate("devices_never"))})>0',
            f'last({ref(estate("devices_never"))})=0',
            'WARNING',
            'Active, enabled devices have no stored backup yet.',
            'freshness',
            'notice',
            depends=base,
            opdata='Devices: {ITEM.LASTVALUE1}',
        ),
        Trigger(
            'DeviceVault: backups are slow (p95 over {$DV.DURATION.MAX})',
            f'last({ref(estate("duration_total_p95"))})>{{$DV.DURATION.MAX}} and last({ref(estate("finished_24h"))})>0',
            f'last({ref(estate("duration_total_p95"))})<={{$DV.DURATION.MAX}} or last({ref(estate("finished_24h"))})=0',
            'WARNING',
            'The 95th percentile request-to-stored time of the last 24h is above {$DV.DURATION.MAX}.',
            'timing',
            'performance',
            depends=base,
            opdata='p95: {ITEM.LASTVALUE1}',
        ),
        Trigger(
            'DeviceVault: clock differs from Zabbix by more than {$DV.SKEW.MAX}s',
            f'fuzzytime({ref(estate("server_time"))},{{$DV.SKEW.MAX}})=0',
            f'fuzzytime({ref(estate("server_time"))},{{$DV.SKEW.MAX}})=1',
            'WARNING',
            "The orchestrator's clock and the Zabbix server's differ; schedules and ages will be off.",
            'system',
            'availability',
            depends=base,
        ),
        Trigger(
            'DeviceVault: push refusals spiking',
            f'last({ref(estate("push_refused_24h"))})-last({ref(estate("push_refused_24h"))},#1:now-1h)>{{$DV.PUSH.REFUSED.MAX}}',
            f'last({ref(estate("push_refused_24h"))})-last({ref(estate("push_refused_24h"))},#1:now-1h)<={{$DV.PUSH.REFUSED.MAX}}',
            'WARNING',
            'Receivers refused more than {$DV.PUSH.REFUSED.MAX} pushes in the last hour (unknown sources, failed '
            'authentication, wrong protocol...). See the Push refusals page.',
            'push',
            'security',
            depends=base,
        ),  # fmt: skip
        leader,
        Trigger(
            'DeviceVault: scheduler is not ticking',
            f'last({ref(estate("scheduler_tick_age"))})>2m or last({ref(estate("scheduler_tick_age"))})<0',
            f'last({ref(estate("scheduler_tick_age"))})>=0 and last({ref(estate("scheduler_tick_age"))})<=2m',
            'AVERAGE',
            'The scheduler leader has not run its tick for over 2 minutes.',
            'scheduler',
            'availability',
            depends=[*base, leader],
        ),
    ]
    t.graphs = [
        Graph('DeviceVault: Success ratio', [estate(f'success_ratio_{w}') for w in cat.WINDOWS]),
        Graph('DeviceVault: Request to stored time (24h)', [estate(f'duration_total_{s}') for s in cat.STATS]),
        Graph('DeviceVault: Failures by reason (24h)', [estate(f'failures_{r}_24h') for r in jobs.FAILURE_REASONS],
              stacked=True),
        Graph('DeviceVault: Device freshness', [estate(k) for k in ('devices_overdue', 'devices_never')]
              + [estate(f'devices_failing_{n}') for n in cat.FAILING]),
        Graph('DeviceVault: Platform health', [estate(f'workers_{s}') for s in ('online', 'offline', 'pending')]
              + [estate('workers_behind'), estate('scheduler_leader')]),
    ]  # fmt: skip

    for discovery in DISCOVERIES:
        rule = Rule(discovery)
        key = lambda k, d=discovery: prototype_key(d, k)  # noqa: E731
        for metric in cat.metrics(discovery.scope):
            if metric.key in LLD_MACROS:
                continue
            component = discovery.slug if discovery.scope != cat.GROUP else _component(metric)
            tags = _tags(component=component, **{discovery.slug: '{#NAME}'})
            rule.items.append(
                _dependent(
                    name, metric, key(metric.key), f'{discovery.label} {{#NAME}}: {metric.name}',
                    master_key(discovery), f"$.data[?(@.id == '{{#ID}}')].{metric.key}.first()", tags,
                )
            )  # fmt: skip
        rule.triggers = _prototype_triggers(t, discovery, key, base)
        if discovery.scope == cat.GROUP:
            rule.graphs = [
                Graph('Group {#NAME}: Device freshness', [key('devices_overdue'), key('devices_never')]
                      + [key(f'devices_failing_{n}') for n in cat.FAILING]),
                Graph('Group {#NAME}: Success ratio', [key(f'success_ratio_{w}') for w in cat.WINDOWS]),
            ]  # fmt: skip
        t.rules.append(rule)

    t.dashboard = [('graph', graph.name) for graph in t.graphs] + [
        ('prototype', 'Group {#NAME}: Device freshness'),
        ('prototype', 'Group {#NAME}: Success ratio'),
    ]
    return t


def _prototype_triggers(t: _Template, discovery: Discovery, key, base: list[Trigger]) -> list[Trigger]:
    ref = t.ref
    label = f'{discovery.label.lower()} {{#NAME}}'
    if discovery.scope == cat.GROUP:
        failing, recovered = _failing(t, key)
        return [
            _ratio_trigger(t, key, f'{label}: ', '{#NAME}', base),
            Trigger(
                f'DeviceVault: {label}: a device has not backed up for over {{$DV.STALE.MAX}}',
                f'last({ref(key("oldest_success_age"))})>{{$DV.STALE.MAX}}',
                f'last({ref(key("oldest_success_age"))})<={{$DV.STALE.MAX}}',
                'AVERAGE',
                'The stalest active, enabled device of the group last backed up longer ago than {$DV.STALE.MAX}.',
                'freshness',
                'notice',
                '{#NAME}',
                base,
                opdata='Age: {ITEM.LASTVALUE1}',
            ),
            Trigger(
                f'DeviceVault: {label}: devices overdue',
                f'last({ref(key("devices_overdue"))})>0',
                f'last({ref(key("devices_overdue"))})=0',
                'WARNING',
                'Devices of the group have no successful backup as recent as their schedule allows.',
                'freshness',
                'notice',
                '{#NAME}',
                base,
                opdata='Devices: {ITEM.LASTVALUE1}',
            ),
            Trigger(
                f'DeviceVault: {label}: devices failing {{$DV.FAIL.CONSEC}}+ times in a row',
                failing,
                recovered,
                'WARNING',
                'Devices of the group failed their last {$DV.FAIL.CONSEC} or more backups (counted at 1, 3 or 5).',
                'failures',
                'notice',
                '{#NAME}',
                base,
            ),
        ]
    if discovery.scope == cat.WORKER:
        approved = code('worker_status', 'approved')
        status, heartbeat = ref(key('status_code')), ref(key('heartbeat_age'))
        return [
            Trigger(
                f'DeviceVault: {label}: no heartbeat for {{$DV.WORKER.HEARTBEAT.MAX}}',
                f'last({status})={approved} and (last({heartbeat})>{{$DV.WORKER.HEARTBEAT.MAX}} or last({heartbeat})<0)',
                f'last({status})<>{approved} or (last({heartbeat})>=0 and last({heartbeat})<={{$DV.WORKER.HEARTBEAT.MAX}})',
                'AVERAGE',
                'An approved worker has not sent a heartbeat recently: it is down or cannot reach the broker.',
                'worker',
                'availability',
                depends=base,
                opdata='Heartbeat age: {ITEM.LASTVALUE2}',
            ),
            Trigger(
                f'DeviceVault: {label}: pending approval for over {{$DV.PENDING.MAX}}',
                f'last({ref(key("pending_age"))})>{{$DV.PENDING.MAX}}',
                f'last({ref(key("pending_age"))})<={{$DV.PENDING.MAX}}',
                'WARNING',
                'A worker registered and is waiting for an administrator to approve or revoke it (Workers page).',
                'worker',
                'notice',
                depends=base,
            ),
            Trigger(
                f'DeviceVault: {label}: assignment behind for 10 minutes',
                f'min({ref(key("assignment_behind"))},10m)=1 and last({ref(key("assignment_behind"))},#1:now-10m)=1',
                f'last({ref(key("assignment_behind"))})=0',
                'WARNING',
                'The worker has not applied its current assignment for 10 minutes.',
                'worker',
                'notice',
                depends=base,
            ),
        ]  # fmt: skip
    if discovery.scope == cat.TARGET:
        return [
            Trigger(
                f'DeviceVault: {label}: no storage worker online',
                f'last({ref(key("workers_online"))})=0',
                f'last({ref(key("workers_online"))})>0',
                'HIGH',
                'No approved, online storage worker serves the target, so backups for it cannot be stored.',
                'storage',
                'availability',
                depends=base,
            )
        ]
    return []


# --- DeviceVault Device by HTTP ------------------------------------------------------------


DEVICE_DESCRIPTION = """\
DeviceVault backup status of this device, matched on its address ({HOST.IP}) or {$DV.DEVICE.ID}.

Link it to the device hosts Zabbix already monitors. {$DV.RELAY.URL} is the monitoring relay on a DeviceVault receiver
in the zone of the proxy that monitors the host (set it once per zone on a site template that links this one), or
{$DV.URL}/api/monitoring where the proxy can reach DeviceVault directly. {$DV.TOKEN} (a service account's token with
the monitoring scope) is meant to be a global macro.

Generated by DeviceVault from its metric catalogue; see DEPLOYMENT.md, section Monitoring."""

DEVICE_MACROS = [
    _macro('{$DV.RELAY.URL}', 'https://receiver-site-a:8443', 'The monitoring relay of a receiver in this zone (or '
           '{$DV.URL}/api/monitoring for the orchestrator). Set it once per zone on a site template.'),
    _macro('{$DV.DEVICE.ID}', '', "DeviceVault's id for this device, for a host whose interface address is not the "
           'one DeviceVault backs up. Empty: match on {HOST.IP}.'),
    _macro('{$DV.DEVICE.INTERVAL}', '15m', 'How often the device status is polled (snapshots are published every 15m).'),
    _macro('{$DV.DEVICE.NODATA}', '45m', 'No answer for this long (three poll intervals) raises the no-data trigger.'),
    _macro('{$DV.NOTFOUND.ALERT}', '1', '1 reports hosts DeviceVault does not back up; 0 switches that trigger off.'),
    _macro('{$DV.DEVICE.FAIL.CONSEC}', '2', 'Consecutive failed backups that raise the failing trigger.'),
    _macro('{$DV.DEVICE.STALE.MAX}', '0', 'Raise a trigger when the last successful backup is older than this (for '
           'example 2d); 0 switches it off in favour of the schedule-based overdue trigger.'),
    _macro('{$DV.DEVICE.DATA.MAX}', '45m', 'Raise a trigger when the published snapshot answering is older than this.'),
]  # fmt: skip


def _device_template() -> _Template:
    t = _Template(DEVICE_TEMPLATE, DEVICE_DESCRIPTION, macros=DEVICE_MACROS)
    name = t.name
    t.items.append(
        _http(
            name, DEVICE_MASTER_KEY, 'DeviceVault: Get device status',
            '{$DV.RELAY.URL}/device/?ip={HOST.IP}&id={$DV.DEVICE.ID}',
            "The device's answer from DeviceVault's published snapshot (503 when the snapshot is stale).",
            '{$DV.DEVICE.INTERVAL}', history='1h', status_codes='200,503', verify_peer='NO', verify_host='NO',
        )
    )  # fmt: skip
    t.items.append(
        {
            'uuid': _uuid(name, 'item', DEVICE_ERROR_KEY),
            'name': 'DeviceVault: Answer error',
            'type': 'DEPENDENT',
            'key': DEVICE_ERROR_KEY,
            'delay': '0',
            'value_type': 'CHAR',
            'trends': '0',
            'description': '"stale" when the relay has no current snapshot (503), otherwise "none".',
            'preprocessing': [
                {
                    'type': 'JSONPATH',
                    'parameters': ['$.error'],
                    'error_handler': 'CUSTOM_VALUE',
                    'error_handler_params': 'none',
                },
            ],  # fmt: skip
            'master_item': {'key': DEVICE_MASTER_KEY},
            'tags': _tags(component='api'),
        }
    )
    for metric in cat.metrics(cat.DEVICE):
        t.items.append(
            _dependent(
                name, metric, device_key(metric.key), f'DeviceVault: {metric.name}', DEVICE_MASTER_KEY,
                f'$.{metric.key}', _tags(component='backup'),
            )
        )  # fmt: skip

    ref = lambda key: t.ref(device_key(key))  # noqa: E731
    master = t.ref(DEVICE_MASTER_KEY)
    error = t.ref(DEVICE_ERROR_KEY)
    nodata = Trigger(
        'DeviceVault: no data from DeviceVault',
        f'nodata({master},{{$DV.DEVICE.NODATA}})=1 or last({error})="stale"',
        f'nodata({master},{{$DV.DEVICE.NODATA}})=0 and last({error})<>"stale"',
        'WARNING',
        'The relay at {$DV.RELAY.URL} did not answer for {$DV.DEVICE.NODATA}, refused the token, or has no current '
        'snapshot (503 stale). The other DeviceVault triggers of this host depend on this one.',
        'api',
        'availability',
    )
    found, enabled, lifecycle = ref('found'), ref('enabled'), ref('lifecycle_code')
    active = code('lifecycle', 'active')
    gate = f'last({found})=1 and last({enabled})=1 and last({lifecycle})={active}'
    ungate = f'last({found})<>1 or last({enabled})<>1 or last({lifecycle})<>{active}'
    auth = code('failure_reason', jobs.FAILURE_AUTH)
    t.triggers = [
        nodata,
        Trigger(
            'DeviceVault: not backed up by DeviceVault',
            f'last({found})=0 and {{$DV.NOTFOUND.ALERT}}=1',
            f'last({found})=1 or {{$DV.NOTFOUND.ALERT}}=0',
            'INFO',
            'No device DeviceVault backs up (and the token may see) has this address or id. Set {$DV.NOTFOUND.ALERT} '
            'to 0 on hosts that are not meant to be backed up.',
            'backup',
            'notice',
            depends=[nodata],
        ),
        Trigger(
            'DeviceVault: backup overdue',
            f'last({ref("overdue")})=1 and {gate}',
            f'last({ref("overdue")})=0 or {ungate}',
            'WARNING',
            'The last successful backup is older than the schedule allows.',
            'backup',
            'notice',
            depends=[nodata],
        ),
        Trigger(
            'DeviceVault: backup failing',
            f'last({ref("consecutive_failures")})>={{$DV.DEVICE.FAIL.CONSEC}} and {gate}',
            f'last({ref("consecutive_failures")})<{{$DV.DEVICE.FAIL.CONSEC}} or {ungate}',
            'WARNING',
            'The last {$DV.DEVICE.FAIL.CONSEC} or more backups failed.',
            'backup',
            'notice',
            depends=[nodata],
            opdata='Consecutive failures: {ITEM.LASTVALUE1}',
        ),
        Trigger(
            'DeviceVault: backup authentication failing',
            f'last({ref("failure_reason_code")})={auth} and {gate}',
            f'last({ref("failure_reason_code")})<>{auth} or {ungate}',
            'AVERAGE',
            'The latest backup failed because the device refused the login or enable credentials.',
            'backup',
            'security',
            depends=[nodata],
        ),
        Trigger(
            'DeviceVault: no successful backup for {$DV.DEVICE.STALE.MAX}',
            f'{{$DV.DEVICE.STALE.MAX}}>0 and last({ref("last_success_at")})>0 and '
            f'last({ref("last_success_age")})>{{$DV.DEVICE.STALE.MAX}} and {gate}',
            f'{{$DV.DEVICE.STALE.MAX}}=0 or last({ref("last_success_age")})<={{$DV.DEVICE.STALE.MAX}} or {ungate}',
            'WARNING',
            'A flat threshold on the age of the last successful backup ({$DV.DEVICE.STALE.MAX}, 0 = off).',
            'backup',
            'notice',
            depends=[nodata],
        ),
        Trigger(
            'DeviceVault: DeviceVault data is old',
            f'last({ref("published_age")})>{{$DV.DEVICE.DATA.MAX}}',
            f'last({ref("published_age")})<={{$DV.DEVICE.DATA.MAX}}',
            'WARNING',
            'The snapshot answering was published longer ago than {$DV.DEVICE.DATA.MAX}: the orchestrator has '
            'stopped publishing while the relay still serves.',
            'api',
            'availability',
            depends=[nodata],
        ),
    ]
    t.graphs = [Graph('DeviceVault: Last backup duration', [device_key(k) for k in
                      ('last_duration', 'last_collect_duration', 'last_store_duration')])]  # fmt: skip
    return t


def templates() -> list[_Template]:
    return [_host_template(), _device_template()]


# --- export --------------------------------------------------------------------------------


def _trigger(template: str, trigger: Trigger, prototype: bool = False) -> dict:
    out = {
        'uuid': _uuid(template, 'trigger-prototype' if prototype else 'trigger', trigger.name),
        'expression': trigger.expression,
        'recovery_mode': 'RECOVERY_EXPRESSION',
        'recovery_expression': trigger.recovery,
        'name': trigger.name,
    }
    if trigger.opdata:
        out['opdata'] = trigger.opdata
    out['priority'] = trigger.priority
    out['description'] = trigger.description
    if trigger.depends:
        out['dependencies'] = [dependency.reference() for dependency in trigger.depends]
    out['tags'] = _tags(component=trigger.component, scope=trigger.scope, group=trigger.group)
    return out


def _referenced(template: str, expression: str) -> set[str]:
    return set(re.findall(rf'/{re.escape(template)}/([^,)]+)', expression))


def _place(template: str, items: list[dict], triggers: list[Trigger], prototype: bool) -> list[dict]:
    """Attach single-item triggers to their item, as Zabbix exports them; return the rest."""
    by_key = {item['key']: item for item in items}
    rest = []
    for trigger in triggers:
        keys = _referenced(template, trigger.expression) | _referenced(template, trigger.recovery)
        exported = _trigger(template, trigger, prototype)
        if len(keys) == 1 and (key := next(iter(keys))) in by_key:
            by_key[key].setdefault('triggers' if not prototype else 'trigger_prototypes', []).append(exported)
        else:
            rest.append(exported)
    return rest


def _graph(template: str, graph: Graph, prototype: bool = False) -> dict:
    out = {'uuid': _uuid(template, 'graph-prototype' if prototype else 'graph', graph.name), 'name': graph.name}
    if graph.stacked:
        out['type'] = 'STACKED'
    out['graph_items'] = []
    for n, key in enumerate(graph.keys):
        entry = {'sortorder': str(n)} if n else {}
        entry.update(color=COLOURS[n % len(COLOURS)], item={'host': template, 'key': key})
        out['graph_items'].append(entry)
    return out


def _rule(template: str, rule: Rule) -> dict:
    discovery = rule.discovery
    items = [dict(item) for item in rule.items]
    rest = _place(template, items, rule.triggers, prototype=True)
    out = {
        'uuid': _uuid(template, 'discovery', discovery.slug),
        'name': f'DeviceVault: {discovery.title} discovery',
        'type': 'DEPENDENT',
        'key': f'dv.{discovery.slug}.discovery',
        'delay': '0',
        'lifetime': '7d',
        'description': f'{discovery.title} from {discovery.path}; resources gone for 7 days are deleted.',
        'item_prototypes': items,
    }
    if rest:
        out['trigger_prototypes'] = rest
    if rule.graphs:
        out['graph_prototypes'] = [_graph(template, graph, prototype=True) for graph in rule.graphs]
    out['master_item'] = {'key': master_key(discovery)}
    out['lld_macro_paths'] = [{'lld_macro': macro, 'path': f'$.{key}'} for key, macro in LLD_MACROS.items()]
    out['preprocessing'] = [{'type': 'JSONPATH', 'parameters': ['$.data']}]
    return out


def _valuemaps(template: _Template) -> list[dict]:
    names = {name: value_map for value_map, name in VALUEMAP_NAMES.items()}
    return [
        {
            'uuid': _uuid(template.name, 'valuemap', name),
            'name': name,
            'mappings': [{'value': str(n), 'newvalue': label} for n, label in VALUE_MAPS[names[name]].items()],
        }
        for name in template.valuemaps()
    ]


def _reference(n: int) -> str:
    """The 7.0 widget reference: five capital letters, unique within a dashboard."""
    letters = ''
    for _ in range(5):
        n, rest = divmod(n, 26)
        letters = chr(ord('A') + rest) + letters
    return letters


def _widgets(template: _Template, version: str) -> list[dict]:
    """Two columns of graphs; Zabbix 6.0 dashboards are 24 units wide, 7.0's 72."""
    width = 24 if version == '6.0' else 72
    widgets = []
    for n, (kind, name) in enumerate(template.dashboard):
        widget = {}
        widget['type'] = {
            ('6.0', 'graph'): 'GRAPH_CLASSIC',
            ('6.0', 'prototype'): 'GRAPH_PROTOTYPE',
            ('7.0', 'graph'): 'graph',
            ('7.0', 'prototype'): 'graphprototype',
        }[version, kind]
        if n % 2:
            widget['x'] = str(width // 2)
        if n // 2:
            widget['y'] = str(5 * (n // 2))
        widget['width'] = str(width // 2)
        widget['height'] = '5'
        graph_field = 'graphid' if version == '6.0' else 'graphid.0'
        fields = []
        if kind == 'prototype':
            fields.append({'type': 'INTEGER', 'name': 'columns', 'value': '1'})
        fields.append(
            {
                'type': 'GRAPH' if kind == 'graph' else 'GRAPH_PROTOTYPE',
                'name': graph_field,
                'value': {'host': template.name, 'name': name},
            }
        )
        if version != '6.0':
            fields.append({'type': 'STRING', 'name': 'reference', 'value': _reference(n)})
        widget['fields'] = fields
        widgets.append(widget)
    return widgets


def _template(template: _Template, version: str) -> tuple[dict, list[dict], list[dict]]:
    """(the template entry, its multi-item triggers, its graphs), for ``version``."""
    items = [dict(item) for item in template.items]
    rest = _place(template.name, items, template.triggers, prototype=False)
    out = {
        'uuid': _uuid(template.name, 'template'),
        'template': template.name,
        'name': template.name,
        'description': template.description,
        'groups': [{'name': TEMPLATE_GROUP}],
        'items': items,
    }
    if template.rules:
        out['discovery_rules'] = [_rule(template.name, rule) for rule in template.rules]
    out['tags'] = _tags(**{'class': 'software', 'target': 'devicevault'})
    out['macros'] = template.macros
    if template.dashboard:
        out['dashboards'] = [
            {
                'uuid': _uuid(template.name, 'dashboard', 'overview'),
                'name': 'DeviceVault overview',
                'pages': [{'name': 'Backups and platform', 'widgets': _widgets(template, version)}],
            }
        ]
    out['valuemaps'] = _valuemaps(template)
    return out, rest, [_graph(template.name, graph) for graph in template.graphs]


def export(version: str) -> dict:
    """The Zabbix export document for ``version`` (``VERSIONS``)."""
    if version not in VERSIONS:
        raise ValueError(f'unsupported Zabbix version {version!r}; expected one of {", ".join(VERSIONS)}')
    entries, triggers, graphs = [], [], []
    for template in templates():
        entry, rest, template_graphs = _template(template, version)
        entries.append(entry)
        triggers += rest
        graphs += template_graphs
    group = [{'uuid': _uuid('group', TEMPLATE_GROUP), 'name': TEMPLATE_GROUP}]
    document = {'version': version}
    document['groups' if version == '6.0' else 'template_groups'] = group
    document['templates'] = entries
    if triggers:
        document['triggers'] = triggers
    if graphs:
        document['graphs'] = graphs
    return {'zabbix_export': document}


class _Dumper(yaml.SafeDumper):
    """Block style as Zabbix writes it: indented lists, literal multi-line strings."""

    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)


def _str(dumper, value):
    style = '|' if '\n' in value else None
    return dumper.represent_scalar('tag:yaml.org,2002:str', value, style=style)


_Dumper.add_representer(str, _str)


def render(version: str) -> str:
    """The template file for ``version``, as YAML."""
    return yaml.dump(export(version), Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=1_000_000)
