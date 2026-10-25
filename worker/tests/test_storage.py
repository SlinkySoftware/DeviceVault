import gzip
import io
import os
import uuid

import pytest
from botocore.response import StreamingBody
from botocore.stub import ANY, Stubber
from psycopg import errors as pg_errors
from pydantic import ValidationError

from devicevault_worker.storage.drivers import (
    BackupName,
    StorageError,
    StorageUnavailable,
    get_driver,
    list_drivers,
    postgresql,
)
from devicevault_worker.storage.drivers.s3 import S3Driver

NAME = BackupName(device_key='7-edge', job_id='j1', timestamp='20261023T000000Z', extension='.cfg')


def driver_and_params(key, **settings):
    driver = get_driver(key)
    return driver(), driver.Params.model_validate(settings)


def store(driver, data, name, params):
    return driver.store(io.BytesIO(data), name, params)


def read(driver, ref, params):
    sink = io.BytesIO()
    driver.read(ref, params, sink)
    return sink.getvalue()


def test_bundled_drivers_describe_themselves():
    described = {driver.key: driver.describe() for driver in list_drivers()}

    assert set(described) >= {'filesystem', 'git', 'postgresql', 's3'}
    assert [described[k]['shareable'] for k in ('filesystem', 'git', 'postgresql', 's3')] == [False, False, True, True]
    assert [described[k]['deletes'] for k in ('filesystem', 'git', 'postgresql', 's3')] == [True, False, True, True]
    secret = described['s3']['params_schema']['properties']['secret_access_key']['anyOf'][0]
    assert secret.get('writeOnly') and secret.get('format') == 'password'


@pytest.mark.parametrize('compress', [False, True])
def test_filesystem_roundtrip(volume, compress):
    driver, params = driver_and_params('filesystem', path='site-a/', compress=compress)
    data = b'hostname edge-01\n\x00\xff'

    ref = store(driver, data, NAME, params)

    assert ref.startswith('7-edge/20261023T000000Z-j1.cfg')
    assert read(driver, ref, params) == data
    stored = (volume / 'site-a' / ref).read_bytes()
    assert (gzip.decompress(stored) if compress else stored) == data
    driver.delete(ref, params)
    assert not (volume / 'site-a' / ref).exists()


def test_git_keeps_history_per_device(volume):
    driver, params = driver_and_params('git', path='repo')
    first = store(driver, b'v1\n', NAME, params)
    second = store(driver, b'v2\n', NAME, params)

    assert first != second
    assert (read(driver, first, params), read(driver, second, params)) == (b'v1\n', b'v2\n')
    assert 'repo' in driver.check(params)


@pytest.mark.parametrize('path', ['', '/', '../outside', 'a/../../b'])
def test_local_paths_stay_inside_the_volume(path):
    with pytest.raises(ValidationError):
        get_driver('filesystem').Params(path=path)


@pytest.mark.parametrize('key', ['filesystem', 'git'])
def test_local_refs_cannot_escape_the_target(key):
    driver, params = driver_and_params(key, path='t')
    escaping = '../outside.cfg' if key == 'filesystem' else 'main:../outside.cfg@0000'

    with pytest.raises(StorageError):
        read(driver, escaping, params)
    with pytest.raises(StorageError):
        store(driver, b'x', BackupName('../evil', 'j', 't', '.cfg'), params)


def test_filesystem_check_creates_and_probes_the_directory(volume):
    driver, params = driver_and_params('filesystem', path='new/dir')

    assert driver.check(params).endswith('new/dir is writable')
    assert (volume / 'new' / 'dir').is_dir()


# --- S3 ------------------------------------------------------------------------------


@pytest.fixture
def s3(monkeypatch):
    """An S3Driver whose client is stubbed; returns (driver, params, stubber)."""
    driver, params = driver_and_params(
        's3', bucket='backups', prefix='dv/', region='us-east-1', access_key_id='AK', secret_access_key='SK'
    )
    client = driver.client(params)
    stubber = Stubber(client)
    monkeypatch.setattr(S3Driver, 'client', lambda self, params: client)
    with stubber:
        yield driver, params, stubber


def test_s3_store_read_delete(s3):
    driver, params, stubber = s3
    key = 'dv/7-edge/20261023T000000Z-j1.cfg'
    stubber.add_response('put_object', {}, {'Bucket': 'backups', 'Key': key, 'Body': ANY, 'ChecksumAlgorithm': ANY})
    stubber.add_response('head_object', {'ContentLength': 6}, {'Bucket': 'backups', 'Key': key})
    stubber.add_response(
        'get_object', {'Body': StreamingBody(io.BytesIO(b'config'), 6)}, {'Bucket': 'backups', 'Key': key}
    )
    stubber.add_response('delete_object', {}, {'Bucket': 'backups', 'Key': key})

    assert store(driver, b'config', NAME, params) == key
    assert read(driver, key, params) == b'config'
    driver.delete(key, params)
    stubber.assert_no_pending_responses()


@pytest.mark.parametrize(
    ('code', 'status', 'error'),
    [('AccessDenied', 403, StorageError), ('SlowDown', 503, StorageUnavailable), ('NoSuchBucket', 404, StorageError)],
)
def test_s3_errors_are_classified(s3, code, status, error):
    driver, params, stubber = s3
    stubber.add_client_error('head_bucket', service_error_code=code, http_status_code=status)

    with pytest.raises(error) as raised:
        driver.check(params)

    assert raised.type is error


def test_s3_secret_is_not_in_the_params_repr():
    _, params = driver_and_params('s3', bucket='backups', secret_access_key='very-secret')

    assert 'very-secret' not in repr(params) and 'very-secret' not in params.model_dump_json()


# --- PostgreSQL ------------------------------------------------------------------------

PG = {'host': 'db.example.com', 'database': 'backups', 'username': 'dv'}


@pytest.mark.parametrize(
    ('tls', 'validation', 'sslmode'),
    [
        ('off', 'none', 'disable'),
        ('preferred', 'none', 'prefer'),
        ('forced', 'none', 'require'),
        ('forced', 'ca', 'verify-ca'),
        ('forced', 'full', 'verify-full'),
    ],
)
def test_postgres_tls_settings_map_to_sslmode(tls, validation, sslmode):
    _, params = driver_and_params(
        'postgresql', **PG, tls=tls, certificate_validation=validation, ca_certificate='-----BEGIN CERTIFICATE-----'
    )

    assert params.sslmode == sslmode


@pytest.mark.parametrize(
    'settings',
    [
        {'tls': 'preferred', 'certificate_validation': 'full'},  # validation needs TLS forced
        {'tls': 'forced', 'certificate_validation': 'ca'},  # CA-only validation needs a CA
        {'db_schema': 'public; DROP TABLE x'},
        {'port': 0},
    ],
)
def test_postgres_rejects_bad_settings(settings):
    with pytest.raises(ValidationError):
        driver_and_params('postgresql', **PG, **settings)


def test_postgres_schema_marks_the_password_secret_and_the_ca_multiline():
    properties = get_driver('postgresql').describe()['params_schema']['properties']

    assert properties['password']['anyOf'][0].get('writeOnly')
    assert properties['ca_certificate']['format'] == 'multiline'


@pytest.mark.parametrize(
    ('exc', 'error'),
    [
        (pg_errors.OperationalError('connection refused'), StorageUnavailable),
        (pg_errors.QueryCanceled('statement timeout'), StorageUnavailable),
        (pg_errors.InvalidPassword('password authentication failed'), StorageError),
        (
            pg_errors.OperationalError('connection failed: FATAL:  password authentication failed for user "dv"'),
            StorageError,
        ),
        (pg_errors.OperationalError('connection failed: SSL error: certificate verify failed'), StorageError),
        (pg_errors.OperationalError('server certificate for "db" does not match host name "10.0.0.1"'), StorageError),
        (pg_errors.InvalidCatalogName('database "x" does not exist'), StorageError),
        (pg_errors.InsufficientPrivilege('permission denied'), StorageError),
    ],
)
def test_postgres_errors_are_classified(exc, error):
    assert type(postgresql._error('store', exc)) is error


@pytest.fixture
def postgres():
    """A real database, from DV_TEST_POSTGRES_HOST (and _PORT, _DB, _USER, _PASSWORD); skipped without one."""
    host = os.environ.get('DV_TEST_POSTGRES_HOST')
    if not host:
        pytest.skip('set DV_TEST_POSTGRES_HOST to run against PostgreSQL')
    schema = f'dv_test_{uuid.uuid4().hex[:8]}'
    settings = {
        'host': host,
        'port': int(os.environ.get('DV_TEST_POSTGRES_PORT', '5432')),
        'database': os.environ.get('DV_TEST_POSTGRES_DB', 'devicevault'),
        'username': os.environ.get('DV_TEST_POSTGRES_USER', 'devicevault'),
        'password': os.environ.get('DV_TEST_POSTGRES_PASSWORD', 'devicevault'),
        'tls': 'off',
    }
    driver, params = driver_and_params('postgresql', **settings, db_schema=schema)
    with driver.connect(driver_and_params('postgresql', **settings)[1], 'setup') as connection:
        connection.execute(f'CREATE SCHEMA {schema}')
    yield driver, params, settings
    with driver.connect(driver_and_params('postgresql', **settings)[1], 'teardown') as connection:
        connection.execute(f'DROP SCHEMA {schema} CASCADE')


def test_postgres_roundtrip(postgres):
    driver, params, _ = postgres
    data = bytes(range(256)) * 10

    assert 'no TLS' in driver.check(params)
    ref = store(driver, data, NAME, params)
    assert ref == '7-edge/20261023T000000Z-j1.cfg'
    assert store(driver, data[::-1], NAME, params) == ref  # a retried job replaces its row
    assert read(driver, ref, params) == data[::-1]
    driver.delete(ref, params)
    with pytest.raises(StorageError, match='not found'):
        read(driver, ref, params)


def test_postgres_without_create_table_needs_the_table(postgres):
    driver, params, _ = postgres

    with pytest.raises(StorageError, match='does not exist'):
        driver.check(params.model_copy(update={'create_table': False}))


def test_postgres_bad_password_is_permanent(postgres):
    driver, _, settings = postgres
    _, params = driver_and_params('postgresql', **{**settings, 'password': 'wrong'})

    with pytest.raises(StorageError) as raised:
        driver.check(params)

    assert raised.type is StorageError
