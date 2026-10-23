import pytest
from django.contrib.auth.models import User
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from monitoring import api
from monitoring.models import FlowerEndpoint


def client_for(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f'Token {Token.objects.get_or_create(user=user)[0].key}')
    return client


@pytest.fixture
def admin(db):
    return User.objects.create_user('admin', password='x', is_staff=True)


@pytest.fixture
def local(db):
    return FlowerEndpoint.objects.create(name='Local', slug='local', url='http://flower:5555')


def open_session(admin, endpoint):
    """An admin's client after asking for a Flower session, and the cookie it got."""
    client = client_for(admin)
    resp = client.post(f'/api/flower-endpoints/{endpoint.pk}/session/')
    assert resp.status_code == 200, resp.data
    return client, resp.cookies[api.SESSION_COOKIE]


def auth(cookie=None, uri='/flower/local/dashboard'):
    """The check nginx makes before proxying ``uri``, from a browser holding ``cookie``."""
    client = APIClient()
    if cookie is not None:
        client.cookies[api.SESSION_COOKIE] = cookie.value
    return client.get('/api/flower-auth/', HTTP_X_ORIGINAL_URI=uri)


# --- endpoints --------------------------------------------------------------------


def test_only_admins_manage_endpoints(admin, local):
    viewer = client_for(User.objects.create_user('viewer', password='x'))
    assert viewer.get('/api/flower-endpoints/').status_code == 403
    assert viewer.post(f'/api/flower-endpoints/{local.pk}/session/').status_code == 403

    rows = client_for(admin).get('/api/flower-endpoints/').data
    assert [(row['slug'], row['link']) for row in rows] == [('local', '/flower/local/')]


@pytest.mark.parametrize(
    ('body', 'field'),
    [
        ({'slug': 'Local_1', 'url': 'http://flower:5555', 'proxied': True}, 'slug'),
        ({'slug': 'a', 'url': 'ftp://flower', 'proxied': False}, 'url'),
        ({'slug': 'a', 'url': 'http://flower:5555/flower/a', 'proxied': True}, 'url'),
        ({'slug': 'a', 'url': 'http://user:pw@flower:5555', 'proxied': True}, 'url'),
    ],
)
def test_endpoints_are_validated(admin, body, field):
    resp = client_for(admin).post('/api/flower-endpoints/', {'name': 'X', **body}, format='json')
    assert resp.status_code == 400
    assert field in resp.data


def test_a_direct_endpoint_links_to_its_url(admin):
    body = {'name': 'Remote', 'slug': 'remote', 'url': 'https://flower.example.com/flower/', 'proxied': False}
    resp = client_for(admin).post('/api/flower-endpoints/', body, format='json')
    assert resp.status_code == 201, resp.data
    assert resp.data['link'] == 'https://flower.example.com/flower/'
    assert client_for(admin).post(f'/api/flower-endpoints/{resp.data["id"]}/session/').status_code == 400


# --- proxy authorisation -------------------------------------------------------------


def test_the_session_cookie_is_scoped_to_the_endpoint(admin, local):
    _, cookie = open_session(admin, local)
    assert cookie['path'] == '/flower/local/'
    assert cookie['httponly'] is True
    assert cookie['samesite'] == 'Strict'
    assert cookie['max-age'] == api.SESSION_SECONDS


def test_nginx_is_told_the_upstream_of_an_authorised_request(admin, local):
    _, cookie = open_session(admin, local)
    resp = auth(cookie, uri='/flower/local/api/workers?refresh=1')
    assert resp.status_code == 204
    assert resp[api.UPSTREAM_HEADER] == 'http://flower:5555'


def test_requests_without_a_valid_session_are_refused(admin, local):
    assert auth().status_code == 401
    _, cookie = open_session(admin, local)
    cookie.set(cookie.key, cookie.value[:-2] + 'xx', cookie.coded_value)
    assert auth(cookie).status_code == 401


def test_a_session_opens_only_its_own_endpoint(admin, local):
    other = FlowerEndpoint.objects.create(name='Other', slug='other', url='http://other:5555')
    _, cookie = open_session(admin, local)
    assert auth(cookie, uri='/flower/other/').status_code == 401
    assert auth(cookie, uri='/flower/missing/').status_code == 403
    assert auth(cookie, uri='/api/flower-endpoints/').status_code == 403

    other.proxied = False
    other.save()
    _, cookie = open_session(admin, local)
    assert auth(cookie, uri='/flower/other/').status_code == 403


def test_signing_out_or_losing_admin_ends_the_session(admin, local):
    client, cookie = open_session(admin, local)
    assert client.post('/api/auth/logout/').status_code == 200
    assert auth(cookie).status_code == 401

    _, cookie = open_session(admin, local)
    admin.is_staff = False
    admin.save()
    assert auth(cookie).status_code == 401


def test_sessions_expire(admin, local, monkeypatch):
    _, cookie = open_session(admin, local)
    monkeypatch.setattr(api, 'SESSION_SECONDS', -1)
    assert auth(cookie).status_code == 401
