import pytest

from search.models import SavedSearch

URL = '/api/saved-searches/'


@pytest.fixture
def reader(make_user, client_for, estate):
    user = make_user('reader', grants={estate['group']('Core'): ['view_contents']})
    return user, client_for(user)


def test_saved_searches_are_private_to_their_owner(reader, make_user, client_for, search_on):
    user, client = reader
    other = client_for(make_user('other'))

    created = client.post(URL, {'name': 'Helpers', 'query': 'ip helper-address'}, format='json')

    assert created.status_code == 201 and created.json()['mode'] == 'text'
    assert [s['name'] for s in client.get(URL).json()] == ['Helpers']
    assert other.get(URL).json() == []
    assert other.delete(f'{URL}{created.json()["id"]}/').status_code == 404
    assert SavedSearch.objects.get().owner == user


def test_saved_searches_can_be_renamed_and_deleted(reader, search_on):
    _, client = reader
    saved = client.post(URL, {'name': 'Helpers', 'query': 'ip helper-address'}, format='json').json()

    renamed = client.patch(f'{URL}{saved["id"]}/', {'name': 'DHCP helpers'}, format='json')
    assert renamed.status_code == 200 and renamed.json()['query'] == 'ip helper-address'
    assert client.delete(f'{URL}{saved["id"]}/').status_code == 204
    assert not SavedSearch.objects.exists()


def test_secret_searches_cannot_be_saved(reader, search_on):
    _, client = reader

    reply = client.post(URL, {'name': 'Old key', 'query': 'cisco', 'mode': 'secret'}, format='json')

    assert reply.status_code == 400 and 'never kept' in str(reply.json()['mode'])
    assert not SavedSearch.objects.exists()


@pytest.mark.parametrize(
    ('body', 'field'),
    [
        ({'name': 'Short', 'query': 'ab'}, 'query'),
        ({'name': 'Bad regex', 'query': '(?=x)', 'mode': 'regex'}, 'query'),
        ({'name': '', 'query': 'hostname'}, 'name'),
    ],
)
def test_saved_searches_are_validated_like_searches(reader, search_on, body, field):
    _, client = reader

    reply = client.post(URL, body, format='json')

    assert reply.status_code == 400 and field in reply.json()


def test_names_are_unique_per_user(reader, make_user, client_for, search_on):
    _, client = reader
    client.post(URL, {'name': 'Helpers', 'query': 'ip helper-address'}, format='json')

    assert client.post(URL, {'name': 'helpers ', 'query': 'hostname'}, format='json').status_code == 400
    other = client_for(make_user('other'))
    assert other.post(URL, {'name': 'Helpers', 'query': 'hostname'}, format='json').status_code == 201


def test_a_saved_search_names_only_device_groups_the_user_can_see(reader, estate, search_on):
    _, client = reader
    core, branch = estate['group']('Core'), estate['group']('Branch')

    ok = client.post(URL, {'name': 'Core', 'query': 'hostname', 'device_group': core.pk}, format='json')
    assert ok.status_code == 201 and ok.json()['device_group_name'] == 'Core'
    hidden = client.post(URL, {'name': 'Branch', 'query': 'hostname', 'device_group': branch.pk}, format='json')
    assert hidden.status_code == 400 and 'device_group' in hidden.json()


def test_saved_searches_are_not_there_when_search_is_off(reader):
    _, client = reader

    assert client.get(URL).status_code == 404
