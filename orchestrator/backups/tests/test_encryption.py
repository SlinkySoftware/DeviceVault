import pytest
from django.core import checks
from django.db import connection

from backups import content
from backups.jobs import JobError, collect_payload, create_job
from backups.models import BackupJob
from core import keys
from core.signing import public_key
from credentials.models import Credential, CredentialType
from devicevault_protocol import signing
from devicevault_protocol.crypto import EncryptionHeader, VaultPublicKey, encrypt_backup, unseal
from devicevault_protocol.tasks import verify_task
from locations.models import BackupLocation

ORCHESTRATOR = lambda: signing.public_key_from_b64(public_key())  # noqa: E731


@pytest.fixture
def encrypted(settings):
    settings.DEVICEVAULT_PAYLOAD_ENCRYPTION = True


@pytest.fixture
def credential(setup):
    cred = Credential.objects.create(
        name='ssh', credential_type=CredentialType.objects.create(name='Local'), data={'password': 's3cret'}
    )
    setup['device'].credential = cred
    setup['device'].save()
    return cred


# --- at rest -----------------------------------------------------------------------


def raw_column(table, column, pk):
    with connection.cursor() as cursor:
        cursor.execute(f'SELECT {column} FROM {table} WHERE id = %s', [pk])  # noqa: S608 (test-only, fixed names)
        return cursor.fetchone()[0]


def test_credentials_and_location_config_are_encrypted_at_rest(credential, setup):
    stored = raw_column('credentials_credential', 'data', credential.pk)
    location = setup['device'].backup_location

    assert 's3cret' not in stored and stored.startswith('"dv1:test:')
    assert '/srv' not in raw_column('locations_backuplocation', 'config', location.pk)
    assert Credential.objects.get(pk=credential.pk).data == {'password': 's3cret'}
    assert BackupLocation.objects.get(pk=location.pk).config == {'path': '/srv'}


def test_ciphertext_is_bound_to_its_column(credential, setup):
    location = setup['device'].backup_location
    stolen = raw_column('credentials_credential', 'data', credential.pk)
    with connection.cursor() as cursor:
        cursor.execute('UPDATE locations_backuplocation SET config = %s WHERE id = %s', [stolen, location.pk])

    with pytest.raises(Exception, match='failed authentication'):
        BackupLocation.objects.get(pk=location.pk)


# --- in transit -----------------------------------------------------------------------


def test_without_payload_encryption_secrets_travel_in_plaintext(credential, setup, broker):
    job, _ = create_job(setup['device'])

    payload = collect_payload(job)

    assert payload['credentials'] == {'password': 's3cret'} and payload['encryption'] is None
    assert verify_task(payload['store']['envelope'], ORCHESTRATOR())['config'] == {'path': '/srv'}


def test_secrets_are_sealed_to_each_eligible_worker(encrypted, credential, setup, broker, worker_keys):
    from core import workers
    from devices.models import CollectionGroup

    elsewhere = worker_keys('collector-elsewhere')
    other_group = CollectionGroup.objects.create(name='Other', rabbitmq_queue_id='other')
    workers.approve(workers.handle_event(elsewhere.event()), role='collector', collection_groups=[other_group])
    job, _ = create_job(setup['device'])

    payload = collect_payload(job)

    assert 'credentials' not in payload
    assert set(payload['credentials_sealed']) == {setup['collector'].id}
    opened = unseal(payload['credentials_sealed'][setup['collector'].id], setup['collector'].encryption)
    assert opened == {'password': 's3cret'}
    store = verify_task(payload['store']['envelope'], ORCHESTRATOR())
    assert 'config' not in store
    assert unseal(store['config_sealed'][setup['storage'].id], setup['storage'].encryption) == {'path': '/srv'}
    assert payload['encryption'] == {'kid': 'test', 'public_key': keys.vault().public_key_b64()}


def test_jobs_need_an_approved_worker_to_seal_for(encrypted, setup, broker):
    setup['group'].workers.clear()

    with pytest.raises(JobError, match='no approved collector'):
        create_job(setup['device'])


def stored_job(setup, **fields):
    return BackupJob.objects.create(
        device=setup['device'], driver='noop', state=BackupJob.STORED, storage_ref='ref', **fields
    )


def test_encrypted_content_is_decrypted_for_its_own_job_only(setup, monkeypatch):
    job = stored_job(setup, encrypted=True)
    other = stored_job(setup, encrypted=True)
    vault = VaultPublicKey(keys.vault().current_kid, keys.vault().public_key_b64())
    blob, _ = encrypt_backup(b'hostname edge-01\n', vault, aad_fields={'job_id': str(job.id)})
    monkeypatch.setattr(content, 'read_raw', lambda j: blob)

    assert EncryptionHeader.from_bytes(blob).aad['job_id'] == str(job.id)
    assert content.read_content(job) == b'hostname edge-01\n'
    with pytest.raises(content.ContentUnavailable, match='different job'):
        content.read_content(other)


def test_an_encrypted_job_never_accepts_plaintext(setup, monkeypatch):
    monkeypatch.setattr(content, 'read_raw', lambda j: b'plaintext')

    with pytest.raises(content.ContentUnavailable, match='should be encrypted'):
        content.read_content(stored_job(setup, encrypted=True))
    assert content.read_content(stored_job(setup)) == b'plaintext'


# --- startup checks ------------------------------------------------------------------------


def run_checks():
    return {message.id for message in checks.run_checks(tags=[checks.Tags.security]) if message.id}


def test_plaintext_payloads_are_flagged_outside_debug(settings):
    settings.DEBUG = False

    assert 'devicevault.W001' in run_checks()


def test_payload_encryption_requires_vault_keys(settings, encrypted):
    settings.DEVICEVAULT_VAULT_KEYS = ''
    keys.vault.cache_clear()
    try:
        assert any(i.startswith('devicevault.E') for i in run_checks())
    finally:
        keys.vault.cache_clear()
