import json
import re
import uuid
from pathlib import Path

import pytest
import yaml
from django.core.management import call_command
from rest_framework.test import APIClient

from monitoring import catalogue, zabbix

DEPLOY = Path(__file__).resolve().parents[3] / 'deploy'
HOST_SCOPES = (catalogue.ESTATE, catalogue.PLATFORM, catalogue.GROUP, catalogue.WORKER, catalogue.TARGET,
               catalogue.RECEIVER)  # fmt: skip


def templates(version):
    document = yaml.safe_load(zabbix.render(version))['zabbix_export']
    return document, {template['template']: template for template in document['templates']}


def item_keys(template):
    keys = {item['key'] for item in template.get('items', [])}
    for rule in template.get('discovery_rules', []):
        keys |= {item['key'] for item in rule['item_prototypes']}
    return keys


def all_triggers(document, template):
    found = list(document.get('triggers', []))
    for item in template.get('items', []):
        found += item.get('triggers', [])
    for rule in template.get('discovery_rules', []):
        found += rule.get('trigger_prototypes', [])
        for item in rule['item_prototypes']:
            found += item.get('trigger_prototypes', [])
    return [trigger for trigger in found if f'/{template["template"]}/' in trigger['expression']]


@pytest.mark.parametrize('version', zabbix.VERSIONS)
def test_the_committed_templates_are_the_generator_output(version):
    committed = zabbix.default_path(version)

    assert committed.read_text() == zabbix.render(version), (
        f'{committed.name} is out of date: run `make zabbix-template` and commit the result'
    )


@pytest.mark.parametrize('version', zabbix.VERSIONS)
def test_the_export_has_the_versions_shape(version):
    document, by_name = templates(version)

    assert document['version'] == version
    assert ('groups' if version == '6.0' else 'template_groups') in document
    assert set(by_name) == {zabbix.HOST_TEMPLATE, zabbix.DEVICE_TEMPLATE}
    widgets = by_name[zabbix.HOST_TEMPLATE]['dashboards'][0]['pages'][0]['widgets']
    assert {widget['type'] for widget in widgets} == (
        {'GRAPH_CLASSIC', 'GRAPH_PROTOTYPE'} if version == '6.0' else {'graph', 'graphprototype'}
    )


@pytest.mark.parametrize('version', zabbix.VERSIONS)
def test_every_catalogue_metric_is_an_item_or_prototype(version):
    _, by_name = templates(version)
    host, device = item_keys(by_name[zabbix.HOST_TEMPLATE]), item_keys(by_name[zabbix.DEVICE_TEMPLATE])
    discoveries = {d.scope: d for d in zabbix.DISCOVERIES}

    for scope in HOST_SCOPES:
        for metric in catalogue.metrics(scope):
            if scope in discoveries:
                if metric.key in zabbix.LLD_MACROS:
                    continue  # {#ID} and {#NAME}
                assert zabbix.prototype_key(discoveries[scope], metric.key) in host, metric.key
            else:
                assert zabbix.estate_key(metric.key) in host, metric.key
    for metric in catalogue.metrics(catalogue.DEVICE):
        assert zabbix.device_key(metric.key) in device, metric.key


def test_items_follow_the_catalogue_units_value_maps_and_nulls():
    _, by_name = templates('7.0')
    items = {item['key']: item for item in by_name[zabbix.HOST_TEMPLATE]['items']}

    ratio = items['dv.success_ratio_24h']
    assert ratio['units'] == '%' and ratio['value_type'] == 'FLOAT'
    assert [step['type'] for step in ratio['preprocessing']] == ['JSONPATH', 'NOT_MATCHES_REGEX']
    assert all(step['error_handler'] == 'DISCARD_VALUE' for step in ratio['preprocessing'])
    assert items['dv.push_last_at']['units'] == 'unixtime' and items['dv.bytes_held']['units'] == 'B'
    assert items['dv.payload_encryption']['valuemap'] == {'name': 'DeviceVault yes/no'}
    assert items['dv.version']['preprocessing'][-1]['type'] == 'DISCARD_UNCHANGED_HEARTBEAT'
    maps = {vm['name']: vm for vm in by_name[zabbix.DEVICE_TEMPLATE]['valuemaps']}
    reasons = {m['value']: m['newvalue'] for m in maps['DeviceVault failure reason']['mappings']}
    assert reasons == {str(code): label for code, label in catalogue.VALUE_MAPS['failure_reason'].items()}


@pytest.mark.parametrize('version', zabbix.VERSIONS)
def test_references_resolve(version):
    document, by_name = templates(version)

    for template in by_name.values():
        keys = item_keys(template)
        rules = template.get('discovery_rules', [])
        masters = [*template.get('items', []), *[i for rule in rules for i in rule['item_prototypes']], *rules]
        assert {item['master_item']['key'] for item in masters if 'master_item' in item} <= keys
        triggers = all_triggers(document, template)
        names = {trigger['name'] for trigger in triggers}
        for trigger in triggers:
            for expression in (trigger['expression'], trigger['recovery_expression']):
                used = set(re.findall(rf'/{re.escape(template["template"])}/([^,)]+)', expression))
                assert used and used <= keys, (trigger['name'], used - keys)
            assert {dependency['name'] for dependency in trigger.get('dependencies', [])} <= names
            assert {tag['tag'] for tag in trigger['tags']} == {'component', 'scope', 'group'}
        maps = {vm['name'] for vm in template['valuemaps']}
        assert {item['valuemap']['name'] for item in masters if 'valuemap' in item} <= maps
    for rule in by_name[zabbix.HOST_TEMPLATE]['discovery_rules']:
        assert rule['lifetime'] == '7d' and rule['type'] == 'DEPENDENT'


@pytest.mark.parametrize('version', zabbix.VERSIONS)
def test_uuids_are_stable_unique_version_4(version):
    text = zabbix.render(version)
    found = re.findall(r'uuid: ([0-9a-f]+)', text)

    assert len(found) == len(set(found)) > 100
    assert all(uuid.UUID(value).version == 4 for value in found)
    assert zabbix.render(version) == text


def test_the_device_template_polls_the_relay_with_the_token():
    _, by_name = templates('6.0')
    master = next(item for item in by_name[zabbix.DEVICE_TEMPLATE]['items'] if item['type'] == 'HTTP_AGENT')
    macros = {macro['macro'] for template in by_name.values() for macro in template['macros']}

    assert master['url'] == '{$DV.RELAY.URL}/device/?ip={HOST.IP}&id={$DV.DEVICE.ID}'
    assert master['headers'] == [{'name': 'Authorization', 'value': 'Bearer {$DV.TOKEN}'}]
    assert master['verify_peer'] == 'NO' and master['status_codes'] == '200,503'
    assert '{$DV.TOKEN}' not in macros and '{$DV.URL}' not in macros  # global macros, not shadowed


def test_the_recorded_validation_responses_have_the_catalogue_keys():
    responses = DEPLOY / 'zabbix-test' / 'responses'

    def load(name):
        return json.loads((responses / f'{name}.json').read_text())

    summary = set(catalogue.keys(catalogue.ESTATE)) | set(catalogue.keys(catalogue.PLATFORM))
    assert set(load('summary')) == summary
    for name, scope in [('device-groups', catalogue.GROUP), ('workers', catalogue.WORKER),
                        ('storage-targets', catalogue.TARGET), ('receivers', catalogue.RECEIVER)]:  # fmt: skip
        assert all(set(entry) == set(catalogue.keys(scope)) for entry in load(name)['data']), name
    assert set(load('device')) == set(catalogue.keys(catalogue.DEVICE))


def test_the_command_writes_a_version(tmp_path):
    out = tmp_path / 'template.yaml'

    call_command('zabbix_template', '--version', '7.0', '--output', str(out))

    assert out.read_text() == zabbix.render('7.0')


def test_the_endpoint_serves_the_template_as_a_download(setup, service_account, make_token, token_client):
    _, raw = make_token(service_account(), scopes=['monitoring'])
    client = token_client(raw)

    answer = client.get('/api/monitoring/zabbix/template/?version=6.0')

    assert answer.status_code == 200 and answer['Content-Type'].startswith('application/yaml')
    assert answer['Content-Disposition'] == 'attachment; filename="devicevault_zabbix_6.0.yaml"'
    assert answer.content.decode() == zabbix.render('6.0')
    assert client.get('/api/monitoring/zabbix/template/?version=6.4').status_code == 400
    assert client.get('/api/monitoring/zabbix/template/', HTTP_ACCEPT='application/yaml').status_code == 400
    assert APIClient().get('/api/monitoring/zabbix/template/?version=7.0').status_code == 401
