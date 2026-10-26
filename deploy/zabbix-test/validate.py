"""Check the generated Zabbix templates against a real Zabbix server (``make zabbix-validate``).

Runs in the dev image on the ``deploy/zabbix-test`` compose network, standard library only:

1. imports ``/templates/devicevault_zabbix_<version>.yaml`` through the API (``configuration.import``);
2. creates hosts pointing at the stub (``stub.py``): the DeviceVault host, one whose token is
   refused, and three device hosts (found, unknown, relay without a snapshot);
3. waits until every item is supported and holds the recorded value (nulls and absent fields
   discarded, not stored), and until exactly the expected triggers are in problem state;
4. prints a summary and exits non-zero on any difference. ``make`` tears the stack down.
"""

import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ZABBIX_URL = os.environ.get('ZABBIX_URL', 'http://web:8080/api_jsonrpc.php')
STUB_URL = os.environ.get('STUB_URL', 'http://stub:8000')
TOKEN = 'dvt_zabbixte_validation-only-token'
HOST_TEMPLATE, DEVICE_TEMPLATE = 'DeviceVault by HTTP', 'DeviceVault Device by HTTP'
RESPONSES = Path(__file__).resolve().parent / 'responses'
LISTS = {'group': 'device-groups', 'worker': 'workers', 'target': 'storage-targets', 'receiver': 'receivers'}
DYNAMIC = {'dv.server_time', 'dv.computed_at', 'dv.computed_age'}  # set by the stub at answer time
TIMEOUT = 420
SETTLE = 75  # after everything matches, hold on for longer than the no-data periods and check again

HOST_MACROS = {'{$DV.URL}': STUB_URL, '{$DV.TOKEN}': TOKEN, '{$DV.INTERVAL}': '10s', '{$DV.NODATA}': '1m'}
DEVICE_MACROS = {
    '{$DV.RELAY.URL}': f'{STUB_URL}/relay',
    '{$DV.TOKEN}': TOKEN,
    '{$DV.DEVICE.INTERVAL}': '10s',
    '{$DV.DEVICE.NODATA}': '1m',
    '{$DV.DEVICE.STALE.MAX}': '1d',
}
HOSTS = {
    # host: (template, interface address, macros)
    'DeviceVault': (HOST_TEMPLATE, None, HOST_MACROS),
    'DeviceVault refused': (HOST_TEMPLATE, None, {**HOST_MACROS, '{$DV.URL}': f'{STUB_URL}/refused'}),
    'Router found': (DEVICE_TEMPLATE, '192.0.2.10', DEVICE_MACROS),
    'Router unknown': (DEVICE_TEMPLATE, '192.0.2.99', DEVICE_MACROS),
    'Router stale': (DEVICE_TEMPLATE, '192.0.2.53', DEVICE_MACROS),
}
EXPECTED_TRIGGERS = {
    'DeviceVault': {
        'DeviceVault: success ratio below 95% (24h)',
        'DeviceVault: devices never backed up',
        'DeviceVault: backups are slow (p95 over 10m)',
        'DeviceVault: clock differs from Zabbix by more than 60s',
        'DeviceVault: scheduler is not ticking',
        'DeviceVault: group Core: success ratio below 95% (24h)',
        'DeviceVault: group Core: a device has not backed up for over 2d',
        'DeviceVault: group Core: devices overdue',
        'DeviceVault: group Core: devices failing 3+ times in a row',
        'DeviceVault: worker storage-1: no heartbeat for 3m',
        'DeviceVault: worker collector-new: pending approval for over 1h',
        'DeviceVault: storage target local: no storage worker online',
    },
    # Everything else depends on the endpoint trigger, so one problem, not dozens.
    'DeviceVault refused': {'DeviceVault: monitoring API unreachable or refusing'},
    'Router found': {
        'DeviceVault: backup overdue',
        'DeviceVault: backup failing',
        'DeviceVault: backup authentication failing',
        'DeviceVault: no successful backup for 1d',
        'DeviceVault: DeviceVault data is old',
    },
    'Router unknown': {'DeviceVault: not backed up by DeviceVault'},
    'Router stale': {'DeviceVault: no data from DeviceVault'},
}
# Hosts whose HTTP items are meant to fail (the token is refused).
FAILING_HOSTS = {'DeviceVault refused'}
# Seconds one API call may take (within the web image's PHP limit, ZBX_MAXEXECUTIONTIME, 600 by default).
API_TIMEOUT = 540


class Api:
    def __init__(self, url: str):
        self.url, self.auth = url, None

    def call(self, method: str, params):
        body = {'jsonrpc': '2.0', 'method': method, 'params': params, 'id': 1}
        if self.auth and method not in ('apiinfo.version', 'user.login'):
            body['auth'] = self.auth
        request = urllib.request.Request(self.url, json.dumps(body).encode(), {'Content-Type': 'application/json-rpc'})
        # Linking the templates in host.create builds hundreds of items; on a small CI runner that takes minutes.
        with urllib.request.urlopen(request, timeout=API_TIMEOUT) as response:
            answer = json.load(response)
        if 'error' in answer:
            raise RuntimeError(f'{method}: {answer["error"].get("data") or answer["error"]}')
        return answer['result']


def connect() -> tuple[Api, str]:
    api = Api(ZABBIX_URL)
    deadline = time.monotonic() + 300
    while True:
        try:
            version = api.call('apiinfo.version', [])
            api.auth = api.call('user.login', {'username': 'Admin', 'password': 'zabbix'})
            return api, version
        except (OSError, RuntimeError, ValueError) as exc:
            if time.monotonic() > deadline:
                raise SystemExit(f'Zabbix API not ready: {exc}') from exc
            time.sleep(3)


def import_templates(api: Api, version: str) -> None:
    source = Path(f'/templates/devicevault_zabbix_{version}.yaml').read_text()
    both = {'createMissing': True, 'updateExisting': True}
    rules = {
        'templates': both,
        'items': both,
        'discoveryRules': both,
        'triggers': both,
        'graphs': both,
        'valueMaps': both,
        'templateDashboards': both,
        'templateLinkage': {'createMissing': True},
        ('groups' if version == '6.0' else 'template_groups'): {'createMissing': True},
    }
    api.call('configuration.import', {'format': 'yaml', 'rules': rules, 'source': source})


def create_hosts(api: Api) -> dict[str, str]:
    group = api.call('hostgroup.create', {'name': 'DeviceVault validation'})['groupids'][0]
    templates = {
        row['host']: row['templateid']
        for row in api.call('template.get', {'output': ['host'], 'filter': {'host': [HOST_TEMPLATE, DEVICE_TEMPLATE]}})
    }
    if set(templates) != {HOST_TEMPLATE, DEVICE_TEMPLATE}:
        raise SystemExit(f'imported templates missing: found {sorted(templates)}')
    ids = {}
    for host, (template, address, macros) in HOSTS.items():
        params = {
            'host': host,
            'groups': [{'groupid': group}],
            'templates': [{'templateid': templates[template]}],
            'macros': [{'macro': macro, 'value': value} for macro, value in macros.items()],
        }
        if address:
            params['interfaces'] = [
                {'type': 1, 'main': 1, 'useip': 1, 'ip': address, 'dns': '', 'port': '10050'}
            ]  # fmt: skip
        ids[host] = api.call('host.create', params)['hostids'][0]
    return ids


def _recorded(name: str) -> dict:
    return json.loads((RESPONSES / f'{name}.json').read_text())


def expected_values(host: str) -> dict[str, object]:
    """Item key -> the value it should hold (None: no value stored), for the items checked."""
    template = HOSTS[host][0]
    if host in FAILING_HOSTS:
        return {'dv.http.status': 401}
    if template == HOST_TEMPLATE:
        out = {f'dv.{key}': value for key, value in _recorded('summary').items()}
        for slug, name in LISTS.items():
            for entry in _recorded(name)['data']:
                for key, value in entry.items():
                    if key not in ('id', 'name'):
                        out[f'dv.{slug}.{key}[{entry["id"]}]'] = value
        out['dv.http.status'] = 200
        return out
    device = _recorded('device')
    keys = [*device, 'error']
    if host == 'Router found':
        return {f'dv.device.{key}': device.get(key, 'none') for key in keys}
    if host == 'Router unknown':
        answer = {'found': 0, 'published_at': device['published_at'], 'published_age': 120, 'error': 'none'}
    else:
        answer = {'error': 'stale'}
    return {f'dv.device.{key}': answer.get(key) for key in keys}


def _matches(expected, actual: str) -> bool:
    if isinstance(expected, bool | int | float):
        try:
            return math.isclose(float(actual), float(expected), rel_tol=1e-6, abs_tol=0.01)
        except ValueError:
            return False
    return actual == str(expected)


def check(api: Api, hosts: dict[str, str]) -> tuple[list[str], dict]:
    """Every difference from the expected state, and counts for the summary."""
    problems: list[str] = []
    counts = {'items': 0, 'unsupported': 0, 'expected_unsupported': 0, 'values': 0, 'fired': 0, 'rules': 0}
    for host, hostid in hosts.items():
        items = api.call(
            'item.get',
            {'hostids': hostid, 'output': ['key_', 'state', 'error', 'lastclock', 'lastvalue', 'type', 'history']},
        )
        rules = api.call('discoveryrule.get', {'hostids': hostid, 'output': ['key_', 'state', 'error']})
        by_key = {item['key_']: item for item in items}
        counts['items'] += len(items)
        counts['rules'] += len(rules)
        for item in [*items, *rules]:
            if item['state'] != '1':
                continue
            if host in FAILING_HOSTS:
                counts['expected_unsupported'] += 1
            else:
                counts['unsupported'] += 1
                problems.append(f'{host}: {item["key_"]} unsupported: {item["error"]}')
        for key, value in expected_values(host).items():
            item = by_key.get(key)
            if item is None:
                problems.append(f'{host}: no item {key} (discovery not done?)')
                continue
            has_value = item['lastclock'] != '0'
            if value is None:
                if has_value:
                    problems.append(f'{host}: {key} should have no value (null or absent), has {item["lastvalue"]!r}')
            elif not has_value:
                problems.append(f'{host}: {key} has no value yet (expected {value!r})')
            elif key not in DYNAMIC and not _matches(value, item['lastvalue']):
                problems.append(f'{host}: {key} = {item["lastvalue"]!r}, expected {value!r}')
            counts['values'] += 1
        triggers = api.call(
            'trigger.get',
            {'hostids': hostid, 'output': ['description', 'value', 'state', 'error'], 'expandDescription': True},
        )
        for trigger in triggers:
            # Unknown is expected where the items fail on purpose, and for triggers comparing with values
            # older than the test has run (an hour ago, ten minutes ago).
            if trigger['state'] == '1' and host not in FAILING_HOSTS and 'not enough data' not in trigger['error']:
                problems.append(f'{host}: trigger {trigger["description"]!r} unknown: {trigger["error"]}')
        fired = {trigger['description'] for trigger in triggers if trigger['value'] == '1'}
        counts['fired'] += len(fired)
        for name in sorted(EXPECTED_TRIGGERS[host] - fired):
            problems.append(f'{host}: trigger {name!r} did not fire')
        for name in sorted(fired - EXPECTED_TRIGGERS[host]):
            problems.append(f'{host}: trigger {name!r} fired unexpectedly')
    return problems, counts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', required=True, choices=['6.0', '7.0'])
    args = parser.parse_args()

    api, server = connect()
    if not server.startswith(f'{args.version}.'):
        raise SystemExit(f'expected Zabbix {args.version}, the API is {server}')
    import_templates(api, args.version)
    print(f'Zabbix {server}: imported {HOST_TEMPLATE!r} and {DEVICE_TEMPLATE!r}', flush=True)
    hosts = create_hosts(api)
    print(f'Created {len(hosts)} hosts; waiting for items and triggers (up to {TIMEOUT}s)', flush=True)

    started = time.monotonic()
    settled_at = None
    while True:
        problems, counts = check(api, hosts)
        elapsed = int(time.monotonic() - started)
        if not problems:
            settled_at = settled_at or time.monotonic()
            if time.monotonic() - settled_at >= SETTLE:
                break
        else:
            settled_at = None
        if elapsed > TIMEOUT:
            break
        time.sleep(10)

    expected = sum(len(names) for names in EXPECTED_TRIGGERS.values())
    print(
        f'Zabbix {server}: {counts["items"]} items and {counts["rules"]} discovery rules on {len(hosts)} hosts, '
        f'{counts["unsupported"]} unsupported ({counts["expected_unsupported"]} on the refused-token host, '
        f'as intended); {counts["values"]} values checked; {counts["fired"]} triggers fired, {expected} expected'
    )
    if problems:
        print(f'FAILED after {elapsed}s:')
        for problem in problems:
            print(f'  - {problem}')
        return 1
    print(f'OK: every item supported with its recorded value, exactly the expected triggers fired ({elapsed}s)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
