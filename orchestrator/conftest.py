import uuid

import pytest
from rest_framework.test import APIClient

from devicevault_protocol import signing
from devicevault_protocol.crypto import ecies


@pytest.fixture(autouse=True)
def published(monkeypatch):
    """Control messages that would have been sent to workers, as (worker_id, envelope)."""
    sent = []
    monkeypatch.setattr('core.workers.publish_control', lambda worker_id, envelope: sent.append((worker_id, envelope)))
    return sent


# Simplified versions of the schemas storage workers publish.
STORAGE_SCHEMAS = {
    'filesystem': {
        'type': 'object',
        'additionalProperties': False,
        'properties': {'path': {'type': 'string', 'minLength': 1}, 'compress': {'type': 'boolean'}},
        'required': ['path'],
    },
    's3': {
        'type': 'object',
        'additionalProperties': False,
        'properties': {
            'bucket': {'type': 'string'},
            'secret_access_key': {
                'anyOf': [{'type': 'string', 'writeOnly': True, 'format': 'password'}, {'type': 'null'}]
            },
        },
        'required': ['bucket'],
    },
}


class WorkerKeys:
    """A fake worker: identity plus a helper to sign events."""

    def __init__(self, name='collector-1'):
        self.id = str(uuid.uuid4())
        self.name = name
        self.key = signing.generate_signing_key()
        self.encryption = ecies.generate_private_key()

    def event(
        self, applied_version=0, drivers=('noop', 'binary_dummy'), storage=('filesystem', 'git', 's3'), **overrides
    ):
        payload = {
            'event': 'heartbeat' if applied_version else 'register',
            'worker_id': self.id,
            'name': self.name,
            'celery_hostname': f'{self.name}@host',
            'hostname': 'host',
            'pid': 42,
            'version': '0.1.0',
            'signing_key': signing.public_key_to_b64(self.key),
            'encryption_key': ecies.public_key_to_b64(self.encryption),
            'capabilities': {
                'collector_drivers': [
                    {
                        'key': key,
                        'name': key.replace('_', ' ').title(),
                        'description': '',
                        'is_binary': key == 'binary_dummy',
                    }
                    for key in drivers
                ],
                'storage_drivers': [
                    {
                        'key': key,
                        'name': key.title(),
                        'shareable': key == 's3',
                        'params_schema': STORAGE_SCHEMAS.get(key),
                    }
                    for key in storage
                ],
            },
            'applied_version': applied_version,
            'queues': [],
            'orchestrator_key': None,
            **overrides,
        }
        return signing.sign(payload, self.key, self.id)


@pytest.fixture
def worker_keys():
    return WorkerKeys


@pytest.fixture
def approved_collector(db):
    """Register and approve a collector offering noop and binary_dummy."""
    from core import workers

    def make(name='collector-1', groups=(), drivers=('noop', 'binary_dummy')):
        keys = WorkerKeys(name)
        worker = workers.handle_event(keys.event(drivers=drivers))
        return workers.approve(worker, role='collector', collection_groups=list(groups))

    return make


# --- users and access -----------------------------------------------------------


@pytest.fixture
def make_user(db):
    """Create a user. ``global_admin`` adds it to Administrators; ``grants`` maps device groups to flags.

    Grants go to a user group of the user's own, and flags pull in what they need (``download`` adds
    ``view_contents`` and ``view``).
    """
    from django.contrib.auth.models import User

    from accounts.access import administrators_group
    from accounts.models import REQUIRES, DeviceGroupGrant, UserGroup, UserGroupMembership

    def implied(flags):
        held = set(flags) | {'view'}
        while True:
            more = held | {need for flag in held for need in REQUIRES[flag]}
            if more == held:
                return held
            held = more

    def make(username, *, global_admin=False, grants=None, password='x', **fields):
        user = User.objects.create_user(username, password=password, **fields)
        if global_admin:
            UserGroupMembership.objects.create(user=user, group=administrators_group())
        if grants:
            group = UserGroup.objects.create(name=f'{username} access')
            UserGroupMembership.objects.create(user=user, group=group)
            for device_group, flags in grants.items():
                DeviceGroupGrant.objects.create(
                    user_group=group, device_group=device_group, **dict.fromkeys(implied(flags), True)
                )
        return user

    return make


@pytest.fixture
def client_for(db):
    """An API client signed in (with a session) as ``user``."""

    def make(user):
        client = APIClient()
        client.force_login(user)
        return client

    return make


@pytest.fixture
def admin_client(make_user, client_for):
    """An API client signed in as a global administrator."""
    return client_for(make_user('admin', global_admin=True))
