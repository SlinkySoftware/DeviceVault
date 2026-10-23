import gzip
import io

import pytest
from botocore.response import StreamingBody
from botocore.stub import Stubber
from pydantic import ValidationError

from devicevault_worker.storage.drivers import BackupName, StorageError, StorageUnavailable, get_driver, list_drivers
from devicevault_worker.storage.drivers.s3 import S3Driver

NAME = BackupName(device_key='7-edge', job_id='j1', timestamp='20261023T000000Z', extension='.cfg')


def driver_and_params(key, **settings):
    driver = get_driver(key)
    return driver(), driver.Params.model_validate(settings)


def test_bundled_drivers_describe_themselves():
    described = {driver.key: driver.describe() for driver in list_drivers()}

    assert set(described) >= {'filesystem', 'git', 's3'}
    assert [described[k]['shareable'] for k in ('filesystem', 'git', 's3')] == [False, False, True]
    secret = described['s3']['params_schema']['properties']['secret_access_key']['anyOf'][0]
    assert secret.get('writeOnly') and secret.get('format') == 'password'


@pytest.mark.parametrize('compress', [False, True])
def test_filesystem_roundtrip(volume, compress):
    driver, params = driver_and_params('filesystem', path='site-a/', compress=compress)
    data = b'hostname edge-01\n\x00\xff'

    ref = driver.store(data, NAME, params)

    assert ref.startswith('7-edge/20261023T000000Z-j1.cfg')
    assert driver.read(ref, params) == data
    stored = (volume / 'site-a' / ref).read_bytes()
    assert (gzip.decompress(stored) if compress else stored) == data
    driver.delete(ref, params)
    assert not (volume / 'site-a' / ref).exists()


def test_git_keeps_history_per_device(volume):
    driver, params = driver_and_params('git', path='repo')
    first = driver.store(b'v1\n', NAME, params)
    second = driver.store(b'v2\n', NAME, params)

    assert first != second
    assert (driver.read(first, params), driver.read(second, params)) == (b'v1\n', b'v2\n')
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
        driver.read(escaping, params)
    with pytest.raises(StorageError):
        driver.store(b'x', BackupName('../evil', 'j', 't', '.cfg'), params)


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
    stubber.add_response('put_object', {}, {'Bucket': 'backups', 'Key': key, 'Body': b'config'})
    stubber.add_response(
        'get_object', {'Body': StreamingBody(io.BytesIO(b'config'), 6)}, {'Bucket': 'backups', 'Key': key}
    )
    stubber.add_response('delete_object', {}, {'Bucket': 'backups', 'Key': key})

    assert driver.store(b'config', NAME, params) == key
    assert driver.read(key, params) == b'config'
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
