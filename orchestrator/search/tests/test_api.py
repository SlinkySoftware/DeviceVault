import pytest
from django.db import connection

from audit.models import AuditLog
from search import indexing, query
from search.tokens import token

URL = '/api/search/'


@pytest.fixture
def indexed(estate):
    """Index a device's backup of ``content``."""

    def make(name, content=None, **device):
        found = estate['device'](name, **device)
        job = estate['backup'](found) if content is None else estate['backup'](found, content)
        indexing.index_job(job)
        return found

    return make


def search(client, q, **params):
    return client.post(URL, {'q': q, **params}, format='json')


def names(reply):
    return [result['device_name'] for result in reply.json()['results']]


def test_search_is_not_there_when_it_is_off(admin_client):
    assert search(admin_client, 'hostname').status_code == 404


def test_the_current_user_says_whether_search_is_on(admin_client, settings):
    assert admin_client.get('/api/auth/user/').json()['config_search'] is False
    settings.DEVICEVAULT_CONFIG_SEARCH = True
    assert admin_client.get('/api/auth/user/').json()['config_search'] is True


def test_text_search_finds_matching_lines_with_their_numbers(admin_client, indexed, search_on):
    edge = indexed('edge-01')
    indexed('edge-02', b'hostname edge-02\n')

    reply = search(admin_client, 'IP HELPER-ADDRESS')

    assert reply.status_code == 200
    [result] = reply.json()['results']
    assert result['device'] == edge.pk and result['device_group_name'] == 'Core' and result['match_count'] == 1
    assert result['lines'] == [{'number': 9, 'text': ' ip helper-address 10.0.0.5'}]
    assert reply.json()['searched_devices'] == 2


def test_a_line_typed_with_its_secret_finds_the_device(admin_client, indexed, search_on):
    indexed('edge-01')
    indexed('edge-02', b'snmp-server community private RO\n')

    assert names(search(admin_client, 'snmp-server community public RO')) == ['edge-01']
    assert names(search(admin_client, 'snmp-server community publ')) == []  # a secret matches only in full
    assert names(search(admin_client, 'snmp-server community')) == ['edge-01', 'edge-02']


def test_a_secret_is_not_found_by_its_value_alone_in_text_mode(admin_client, indexed, search_on):
    indexed('edge-01')

    assert names(search(admin_client, 'public')) == []


def test_result_lines_show_tokens_not_secrets(admin_client, indexed, search_on):
    indexed('edge-01')

    [line] = search(admin_client, 'snmp-server community').json()['results'][0]['lines']
    assert line['text'] == f'snmp-server community {token("public")} RO'


def test_a_pasted_result_line_finds_itself(admin_client, indexed, search_on):
    indexed('edge-01')

    assert names(search(admin_client, f'community {token("public")}')) == ['edge-01']


def test_regex_search_matches_per_line_case_insensitively(admin_client, indexed, search_on):
    indexed('edge-01')
    indexed('edge-02', b'interface Gi0/1\n ip address 10.99.0.1 255.255.255.0\n')

    reply = search(admin_client, r'^\s*ip address 10\.12\.\d+\.\d+', mode='regex')
    assert names(reply) == ['edge-01'] and reply.json()['results'][0]['lines'][0]['number'] == 8
    assert names(search(admin_client, r'^HOSTNAME\b', mode='regex')) == ['edge-01']
    assert names(search(admin_client, r'community \S+ ro$', mode='regex')) == ['edge-01']
    # "." does not cross lines.
    assert names(search(admin_client, r'location.*helper', mode='regex')) == []


@pytest.mark.parametrize(
    ('params', 'message'),
    [
        ({'q': 'ab'}, 'at least 3'),
        ({'q': '   '}, 'at least 3'),
        ({'q': 'a\nb c'}, 'one line'),
        ({'q': '(unclosed', 'mode': 'regex'}, 'Invalid regular expression'),
        ({'q': '(?=lookahead)', 'mode': 'regex'}, 'Invalid regular expression'),
    ],
)
def test_bad_searches_are_refused(admin_client, search_on, params, message):
    reply = admin_client.post(URL, params, format='json')

    assert reply.status_code == 400 and message in reply.json()['detail']


def test_unknown_modes_and_long_queries_are_refused(admin_client, search_on):
    assert search(admin_client, 'hostname', mode='glob').status_code == 400
    assert search(admin_client, 'x' * (query.MAX_QUERY_LENGTH + 1)).status_code == 400


def test_only_devices_whose_contents_the_user_may_see_are_searched(make_user, client_for, indexed, estate, search_on):
    indexed('core-01', group_name='Core')
    indexed('branch-01', group_name='Branch')
    indexed('loose-01', group_name=None)
    reader = client_for(make_user('reader', grants={estate['group']('Core'): ['view_contents']}))
    viewer = client_for(make_user('viewer', grants={estate['group']('Branch'): ['view']}))

    reply = search(reader, 'hostname')
    assert names(reply) == ['core-01'] and reply.json()['searched_devices'] == 1
    assert names(search(viewer, 'hostname')) == [] and search(viewer, 'hostname').json()['searched_devices'] == 0


def test_filters_by_device_group_and_driver(admin_client, indexed, estate, search_on):
    indexed('core-01', group_name='Core')
    indexed('branch-01', group_name='Branch')
    indexed('noop-01', b'hostname noop\n', group_name='Branch', driver='noop')

    assert names(search(admin_client, 'hostname', device_group=estate['group']('Branch').pk)) == [
        'branch-01',
        'noop-01',
    ]
    assert names(search(admin_client, 'hostname', driver='noop')) == ['noop-01']


def test_binary_backups_are_not_searched(admin_client, estate, search_on):
    device = estate['device']('ups', driver='noop')
    indexing.index_job(estate['backup'](device, b'hostname\x00', is_binary=True))

    reply = search(admin_client, 'hostname')
    assert names(reply) == [] and reply.json()['searched_devices'] == 0


def test_results_are_capped(admin_client, indexed, search_on, monkeypatch):
    monkeypatch.setattr(query, 'MAX_DEVICES', 2)
    monkeypatch.setattr(query, 'MAX_LINES', 1)
    for name in ('a-01', 'b-01', 'c-01'):
        indexed(name, b'ntp server 1\nntp server 2\n')

    reply = search(admin_client, 'ntp server').json()
    assert [r['device_name'] for r in reply['results']] == ['a-01', 'b-01'] and reply['truncated'] is True
    assert reply['results'][0]['match_count'] == 2 and len(reply['results'][0]['lines']) == 1


def test_searches_are_audited_without_the_secrets_typed(admin_client, indexed, search_on):
    edge = indexed('edge-01')

    search(admin_client, 'snmp-server community public RO')
    search(admin_client, r'^hostname', mode='regex')

    text, regex = AuditLog.objects.filter(action='search.query').order_by('id')
    assert text.details['query'] == f'snmp-server community {token("public")} RO'
    assert 'public' not in str(text.details) and text.details['devices'] == 1
    assert regex.details == {
        'mode': 'regex',
        'query': '^hostname',
        'device_group': None,
        'driver': None,
        'devices': 1,
        'device_ids': [edge.pk],
        'truncated': False,
    }


def test_signed_out_users_cannot_search(db, search_on):
    from rest_framework.test import APIClient

    assert APIClient().post(URL, {'q': 'hostname'}, format='json').status_code == 401


def test_searching_needs_the_csrf_token(make_user, search_on):
    from rest_framework.test import APIClient

    client = APIClient(enforce_csrf_checks=True)
    client.force_login(make_user('reader', global_admin=True))
    assert client.post(URL, {'q': 'hostname'}, format='json').status_code == 403


def test_searches_are_not_gets(admin_client, search_on):
    assert admin_client.get(URL, {'q': 'hostname'}).status_code == 405


@pytest.mark.parametrize(
    ('pattern', 'postgres'),
    [
        (r'\bpublic\b', r'\ypublic\y'),
        (r'\Ahostname\z', r'^hostname$'),
        (r'(?P<name>\d+)', r'(\d+)'),
        (r'\\b', r'\\b'),
        (r'a\.b', r'a\.b'),
    ],
)
def test_regexes_are_translated_for_postgresql(pattern, postgres):
    assert query.postgres_regex(pattern) == postgres


@pytest.mark.skipif(connection.vendor != 'postgresql', reason='the trigram index is PostgreSQL-only')
@pytest.mark.parametrize('lookup', [{'text__dv_like': '%helper-address%'}, {'text__dv_iregex': '(?n)^hostname'}])
def test_candidate_lookups_use_the_trigram_index(db, lookup):
    from search.models import SearchDocument

    sql, params = SearchDocument.objects.filter(**lookup).values('pk').query.sql_with_params()
    with connection.cursor() as cursor:
        cursor.execute('SET enable_seqscan = off')
        cursor.execute(f'EXPLAIN {sql}', params)
        plan = '\n'.join(row[0] for row in cursor.fetchall())
    assert 'search_document_text_trgm' in plan
