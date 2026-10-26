"""The monitoring figures in Prometheus text exposition format (version 0.0.4).

Series come from the catalogue's ``prometheus`` names and labels. Device-group
series are their own families (``devicevault_group_*``, labelled ``device_group``)
so that summing them never double-counts the estate figures. There are no
per-device series: cardinality stays bounded, and per-device status belongs to
the Zabbix device template.
"""

from collections import defaultdict

from monitoring.catalogue import COUNTER, ESTATE, GROUP, PLATFORM, RECEIVER, TARGET, WORKER, metrics

CONTENT_TYPE = 'text/plain; version=0.0.4; charset=utf-8'

# The label naming each entry of a list section.
ENTRY_LABELS = {GROUP: 'device_group', WORKER: 'worker', TARGET: 'storage_target', RECEIVER: 'receiver'}


def _escape(value: str) -> str:
    return value.replace('\\', '\\\\').replace('\n', '\\n').replace('"', '\\"')


def _family(name: str, scope: str) -> str:
    if scope == GROUP:
        return name.replace('devicevault_', 'devicevault_group_', 1)
    return name


class Exposition:
    def __init__(self):
        self.families: dict[str, dict] = {}
        self.samples: dict[str, list[str]] = defaultdict(list)

    def add(self, scope: str, figures: dict, extra_labels: dict[str, str] | None = None) -> None:
        for metric in metrics(scope):
            value = figures.get(metric.key)
            if metric.prometheus is None or value is None or isinstance(value, str):
                continue
            name = _family(metric.prometheus, scope)
            self.families.setdefault(name, {'kind': metric.kind, 'help': metric.description})
            labels = {**(extra_labels or {}), **metric.labels}
            rendered = ','.join(f'{key}="{_escape(str(label))}"' for key, label in labels.items())
            self.samples[name].append(
                f'{name}{{{rendered}}} {float(value):g}' if rendered else f'{name} {float(value):g}'
            )

    def render(self) -> str:
        lines = []
        for name, family in self.families.items():
            lines.append(f'# HELP {name} {_escape(family["help"])}')
            lines.append(f'# TYPE {name} {"counter" if family["kind"] == COUNTER else "gauge"}')
            lines.extend(self.samples[name])
        return '\n'.join(lines) + '\n'


def render(summary: dict, groups: list[dict], platform: dict | None, lists: dict[str, list[dict]]) -> str:
    """``lists`` maps WORKER, TARGET and RECEIVER to their entries (empty without the platform scope)."""
    out = Exposition()
    out.add(ESTATE, summary)
    for entry in groups:
        out.add(GROUP, entry, {'device_group': entry['name']})
    if platform is not None:
        out.add(PLATFORM, platform)
    for scope, entries in lists.items():
        for entry in entries:
            out.add(scope, entry, {ENTRY_LABELS[scope]: entry['name']})
    return out.render()
