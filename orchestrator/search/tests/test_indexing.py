import fakeredis
import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone

from backups.content import ContentUnavailable
from core import keys
from core.signing import sign_task
from core.tasks import SEARCH_INDEX_TASK, change_summary, search_index
from devicevault_protocol import signing
from devicevault_protocol.tasks import sign_task as sign_with
from search import indexing
from search.models import SearchDocument
from search.tokens import token


@pytest.fixture
def sent(monkeypatch):
    """Index tasks queued, as job ids."""
    tasks = []

    def send(name, args=None, queue=None, **kwargs):
        assert name == SEARCH_INDEX_TASK
        tasks.append(signing.peek(args[0])['job_id'])

    monkeypatch.setattr('search.indexing.celery_app.send_task', send)
    return tasks


@pytest.fixture
def redis(monkeypatch):
    server = fakeredis.FakeRedis()
    monkeypatch.setattr(indexing, '_redis', lambda: server)
    return server


@pytest.fixture(autouse=True)
def fresh_pass(monkeypatch):
    monkeypatch.setattr(indexing, '_last_catch_up', None)


def document(device):
    return SearchDocument.objects.get(device=device)


def test_a_backup_is_indexed_with_its_secrets_as_tokens(estate):
    device = estate['device']('edge-01')
    job = estate['backup'](device)

    indexing.index_job(job)

    text = document(device).text
    assert 'public' not in text and f'snmp-server community {token("public")} RO' in text
    assert f'username ops password 7 {token("cisco")}' in text
    # Volatile lines are kept, so line numbers match the backup itself.
    assert text.split('\n')[:3] == ['Building configuration...', '!', 'hostname edge-01']
    assert document(device).job == job and document(device).token_kid == 'test'


def test_crlf_and_invalid_utf8_are_normalised(estate):
    device = estate['device']('edge-01')

    indexing.index_job(estate['backup'](device, b'hostname a\r\nbanner \xff\r\n'))

    assert document(device).text == 'hostname a\nbanner �\n'


def test_an_older_backup_does_not_replace_a_newer_one(estate):
    device = estate['device']('edge-01')
    new = estate['backup'](device, b'hostname new\n')
    old = estate['backup'](device, b'hostname old\n', hours=2)

    indexing.index_job(new)
    indexing.index_job(old)

    assert document(device).job == new and 'new' in document(device).text


def test_binary_and_large_backups_are_recorded_as_not_searchable_without_reading(estate, contents):
    binary = estate['device']('ups', driver='noop')
    large = estate['device']('edge-02')
    big = estate['backup'](large, b'x')
    big.size_bytes = indexing.MAX_INDEX_BYTES + 1

    indexing.index_job(estate['backup'](binary, b'\x00\x01', is_binary=True))
    indexing.index_job(big)

    assert document(binary).skipped == 'binary backup' and document(binary).text == ''
    assert document(large).skipped == 'larger than 16 MiB'
    assert contents.reads == []


def test_an_unchanged_unencrypted_backup_moves_the_document_without_reading(estate, contents):
    device = estate['device']('edge-01')
    first = estate['backup'](device, hours=1, encrypted=False)
    indexing.index_job(first)
    second = estate['backup'](device, encrypted=False)

    indexing.index_job(second)

    assert contents.reads == [first.pk]
    assert document(device).job == second and 'hostname edge-01' in document(device).text


def test_reindexing_the_same_backup_does_nothing(estate, contents):
    device = estate['device']('edge-01')
    job = estate['backup'](device)

    indexing.index_job(job)
    indexing.index_job(job)

    assert contents.reads == [job.pk]


def test_the_summary_task_indexes_from_the_same_read(estate, contents, search_on):
    device = estate['device']('edge-01')
    previous = estate['backup'](device, b'hostname edge-01\n', hours=1)
    job = estate['backup'](device)

    change_summary.apply(args=[sign_task({'job_id': str(job.id)})])

    job.refresh_from_db()
    assert job.changed is True and document(device).job == job
    assert sorted(contents.reads, key=str) == sorted([job.pk, previous.pk], key=str)


def test_the_summary_task_does_not_index_with_search_off(estate, contents):
    device = estate['device']('edge-01')
    job = estate['backup'](device)

    change_summary.apply(args=[sign_task({'job_id': str(job.id)})])

    assert not SearchDocument.objects.exists()


def test_the_index_task_needs_the_orchestrators_signature(estate, search_on):
    job = estate['backup'](estate['device']('edge-01'))
    forged = sign_with({'job_id': str(job.id)}, signing.generate_signing_key())

    search_index.apply(args=[forged])
    assert not SearchDocument.objects.exists()

    search_index.apply(args=[sign_task({'job_id': str(job.id)})])
    assert document(job.device).job == job


def test_the_index_task_retries_then_gives_up_on_unreadable_backups(estate, contents, search_on):
    job = estate['backup'](estate['device']('edge-01'), ContentUnavailable('storage offline'))

    search_index.apply(args=[sign_task({'job_id': str(job.id)})])

    assert len(contents.reads) == 4 and not SearchDocument.objects.exists()


def test_stale_documents_are_found(estate, catalogue, monkeypatch):
    missing = estate['device']('missing')
    estate['backup'](missing)
    behind = estate['device']('behind')
    indexing.index_job(estate['backup'](behind, hours=2))
    newest = estate['backup'](behind)
    current = estate['device']('current')
    indexing.index_job(estate['backup'](current))
    estate['device']('never-backed-up')

    assert sorted(indexing.stale_jobs()) == sorted(
        [(missing.pk, str(missing.backup_jobs.get().pk)), (behind.pk, str(newest.pk))]
    )

    catalogue['cisco_ios']['secret_lines'] = catalogue['cisco_ios']['secret_lines'][:1]
    assert current.pk in {device_id for device_id, _ in indexing.stale_jobs()}


def test_a_rotated_data_key_makes_documents_stale(estate, monkeypatch):
    device = estate['device']('edge-01')
    indexing.index_job(estate['backup'](device))
    assert indexing.stale_jobs() == []

    monkeypatch.setattr(keys, 'search_token_key', lambda: ('next', b'n' * 32))
    assert [device_id for device_id, _ in indexing.stale_jobs()] == [device.pk]


def test_pruned_backups_are_not_indexed(estate):
    device = estate['device']('edge-01')
    estate['backup'](device, pruned_at=timezone.now())

    assert indexing.stale_jobs() == []


def test_the_catch_up_pass_queues_each_stale_device_once_an_hour(estate, sent, redis, search_on, monkeypatch):
    monkeypatch.setattr(indexing, 'CATCH_UP_BATCH', 2)
    jobs = [estate['backup'](estate['device'](f'edge-{n}')) for n in range(3)]
    now = timezone.now()

    assert indexing.catch_up(now) == 2
    assert indexing.catch_up(now) is None  # not due yet
    assert indexing.catch_up(now + indexing.CATCH_UP_INTERVAL) == 1
    assert indexing.catch_up(now + 2 * indexing.CATCH_UP_INTERVAL) == 0
    assert sorted(sent) == sorted(str(job.pk) for job in jobs)


def test_with_search_off_the_catch_up_pass_deletes_every_document(estate, sent):
    indexing.index_job(estate['backup'](estate['device']('edge-01')))

    assert indexing.catch_up(timezone.now()) == 0
    assert not SearchDocument.objects.exists() and sent == []


def test_reindex_queues_every_device(estate, sent, redis, search_on):
    device = estate['device']('edge-01')
    job = estate['backup'](device)
    indexing.index_job(job)
    redis.set(indexing.QUEUED_KEY.format(device=device.pk), 'x')

    call_command('reindex_search')

    assert sent == [str(job.pk)]
    assert document(device).text  # still searchable until rebuilt


def test_reindex_refuses_with_search_off(db):
    with pytest.raises(CommandError, match='DV_CONFIG_SEARCH'):
        call_command('reindex_search')
