import pytest
from django.utils import timezone

from audit.models import AuditLog
from backups.models import BackupJob


@pytest.fixture
def member(setup, make_user, client_for):
    """A client for a user holding ``flags`` on the device's group."""

    def make(*flags):
        user = make_user('-'.join(('member', *flags)), grants={setup['device'].device_group: flags})
        return client_for(user)

    return make


@pytest.fixture
def stored(setup):
    return BackupJob.objects.create(
        device=setup['device'], storage_target=setup['target'], driver='noop', state=BackupJob.STORED
    )


def pin(client, job, pinned=True):
    return client.post(f'/api/backups/{job.id}/pin/', {'pinned': pinned}, format='json')


def annotate(client, job, **body):
    return client.post(f'/api/backups/{job.id}/annotate/', body, format='json')


def test_pinning_needs_the_group_admin_grant(stored, member):
    assert pin(member('view_contents'), stored).status_code == 403
    reply = pin(member('admin'), stored)

    assert reply.status_code == 200
    assert reply.json()['pinned'] and reply.json()['pinned_by_username'] == 'member-admin'
    stored.refresh_from_db()
    assert stored.pinned and stored.pinned_at is not None
    entry = AuditLog.objects.get(action='backup.pin')
    assert entry.details['job'] == str(stored.id) and entry.device_group_id == stored.device.device_group_id


def test_unpinning_clears_who_and_when(stored, member):
    admin = member('admin')
    pin(admin, stored)

    reply = pin(admin, stored, pinned=False)

    assert reply.status_code == 200
    assert (reply.json()['pinned'], reply.json()['pinned_by_username'], reply.json()['pinned_at']) == (
        False,
        None,
        None,
    )
    assert AuditLog.objects.filter(action='backup.unpin').count() == 1


def test_pinning_twice_changes_nothing(stored, member):
    admin = member('admin')
    pin(admin, stored)
    first = BackupJob.objects.get(pk=stored.pk).pinned_at

    assert pin(admin, stored).status_code == 200
    assert BackupJob.objects.get(pk=stored.pk).pinned_at == first
    assert AuditLog.objects.filter(action='backup.pin').count() == 1


def test_only_stored_backups_that_retention_kept_can_be_pinned(setup, stored, admin_client):
    failed = BackupJob.objects.create(
        device=setup['device'], storage_target=setup['target'], driver='noop', state=BackupJob.FAILED
    )
    BackupJob.objects.filter(pk=stored.pk).update(prune_requested_at=timezone.now())

    assert 'stored' in pin(admin_client, failed).json()['error']
    assert 'deleted' in pin(admin_client, stored).json()['error']
    assert not BackupJob.objects.filter(pinned=True).exists()


def test_a_pinned_backup_is_not_deleted_by_retention(setup, stored, admin_client, broker):
    from datetime import timedelta

    from backups.retention import expired_jobs
    from policies.models import RetentionPolicy

    newer = BackupJob.objects.create(
        device=setup['device'], storage_target=setup['target'], driver='noop', state=BackupJob.STORED, storage_ref='b'
    )
    BackupJob.objects.filter(pk=stored.pk).update(storage_ref='a', created_at=newer.created_at - timedelta(days=1))
    policy = RetentionPolicy.objects.create(name='One', max_backups=1, min_backups=1)
    assert expired_jobs(setup['device'], policy, timezone.now()) == [BackupJob.objects.get(pk=stored.pk)]

    pin(admin_client, stored)

    assert expired_jobs(setup['device'], policy, timezone.now()) == []


def test_labels_and_notes_need_view_contents(stored, member):
    assert annotate(member('view'), stored, label='x').status_code == 403
    reply = annotate(member('view_contents'), stored, label='  pre-upgrade 17.9 ', note='Taken before the upgrade.\n')

    assert reply.status_code == 200
    body = reply.json()
    assert (body['label'], body['note'], body['annotated_by_username']) == (
        'pre-upgrade 17.9',
        'Taken before the upgrade.',
        'member-view_contents',
    )
    entry = AuditLog.objects.get(action='backup.annotate')
    assert entry.details['label'] == 'pre-upgrade 17.9' and entry.details['note_changed'] is True
    assert 'Taken before' not in str(entry.details)


def test_annotating_keeps_a_field_left_out(stored, admin_client):
    annotate(admin_client, stored, label='baseline', note='Approved.')

    reply = annotate(admin_client, stored, label='approved baseline')

    assert (reply.json()['label'], reply.json()['note']) == ('approved baseline', 'Approved.')
    assert AuditLog.objects.filter(action='backup.annotate').order_by('pk').last().details['note_changed'] is False


def test_labels_are_one_short_line(stored, admin_client):
    assert annotate(admin_client, stored, label='two\nlines').status_code == 400
    assert annotate(admin_client, stored, label='x' * 65).status_code == 400
    assert annotate(admin_client, stored, note='x' * 2001).status_code == 400


def test_failed_and_pruned_backups_can_be_labelled_but_not_running_ones(setup, admin_client):
    def job(state, **fields):
        return BackupJob.objects.create(
            device=setup['device'], storage_target=setup['target'], driver='noop', state=state, **fields
        )

    assert annotate(admin_client, job(BackupJob.FAILED), label='device was being replaced').status_code == 200
    assert annotate(admin_client, job(BackupJob.STORED, pruned_at=timezone.now()), label='old').status_code == 200
    assert annotate(admin_client, job(BackupJob.COLLECTING), label='soon').status_code == 400


def test_the_list_filters_pinned_and_labelled_backups(setup, stored, admin_client):
    other = BackupJob.objects.create(
        device=setup['device'], storage_target=setup['target'], driver='noop', state=BackupJob.STORED
    )
    pin(admin_client, stored)
    annotate(admin_client, other, label='baseline')

    def ids(query):
        return {job['id'] for job in admin_client.get(f'/api/backups/?{query}').json()['results']}

    assert ids('pinned=true') == {str(stored.id)}
    assert ids('pinned=false') == {str(other.id)}
    assert ids('labelled=true') == {str(other.id)}


def test_backups_of_hidden_devices_cannot_be_pinned_or_labelled(stored, make_user, client_for):
    from devices.models import DeviceGroup

    elsewhere = client_for(make_user('elsewhere', grants={DeviceGroup.objects.create(name='Other'): ['admin']}))

    assert pin(elsewhere, stored).status_code == 404
    assert annotate(elsewhere, stored, label='x').status_code == 404
