"""Storage targets: where backups are written, and which workers write them."""

import uuid

from django.db import models

from core.fields import EncryptedJSONField
from devicevault_protocol.names import storage_target_queue_name


class StorageTarget(models.Model):
    """One place backups go: a storage driver plus its settings, served by chosen workers.

    Each target has its own queue (``storage.target.<id>``) consumed only by
    its workers, so two targets with the same driver never mix. A driver that
    is not ``shareable`` (a directory on one worker's volume) gets one worker.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=128, unique=True)
    description = models.TextField(blank=True)
    driver = models.CharField(max_length=64, help_text='Storage driver key, as advertised by storage workers')
    config = EncryptedJSONField(default=dict, blank=True, help_text='Driver settings (encrypted at rest)')
    workers = models.ManyToManyField('core.Worker', blank=True, related_name='storage_targets')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def queue(self) -> str:
        return storage_target_queue_name(self.id)
