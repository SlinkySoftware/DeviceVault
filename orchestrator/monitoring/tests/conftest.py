from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from backups.models import BackupJob
from backups.tests.conftest import setup  # noqa: F401  (the backed-up device, workers and target)
from core.models import UserProfile


@pytest.fixture
def job(setup):  # noqa: F811
    """Make a job of ``device`` that finished ``ago`` before now, having taken ``took``."""

    def make(state=BackupJob.STORED, *, ago=timedelta(0), took=timedelta(seconds=10), device=None, **fields):
        finished = None if state in BackupJob.ACTIVE_STATES else timezone.now() - ago
        made = BackupJob.objects.create(
            device=device or setup['device'],
            storage_target=setup['target'],
            driver='noop',
            state=state,
            finished_at=finished,
            **fields,
        )
        BackupJob.objects.filter(pk=made.pk).update(created_at=(finished or timezone.now() - ago) - took)
        return made

    return make


@pytest.fixture
def service_account(db):
    """A service account in a user group with ``view`` on ``groups``."""
    from accounts.models import DeviceGroupGrant, UserGroup, UserGroupMembership

    def make(username='zabbix', groups=()):
        user = User.objects.create(username=username)
        user.set_unusable_password()
        user.save()
        UserProfile.objects.create(user=user, is_service_account=True)
        team = UserGroup.objects.create(name=f'{username} access')
        UserGroupMembership.objects.create(user=user, group=team)
        for group in groups:
            DeviceGroupGrant.objects.create(user_group=team, device_group=group, view=True)
        return user

    return make
