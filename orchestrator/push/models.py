"""Receiver settings and the pushes receivers turned away."""

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from core.fields import EncryptedJSONField
from devicevault_protocol.push import DEFAULT_MAX_FILE_SIZE, DEFAULT_SSH_PORT, PROTOCOLS, REASONS

PORT_VALIDATORS = [MinValueValidator(1), MaxValueValidator(65535)]


class ReceiverSettings(models.Model):
    """What one receiver listens for. Sent to it in its assignment (see devicevault_protocol.push)."""

    worker = models.OneToOneField(
        'core.Worker', primary_key=True, on_delete=models.CASCADE, related_name='receiver_settings'
    )
    bind_address = models.GenericIPAddressField(
        null=True, blank=True, unpack_ipv4=True, help_text='Address to listen on (empty: every address)'
    )
    max_file_size = models.PositiveBigIntegerField(
        default=DEFAULT_MAX_FILE_SIZE, validators=[MinValueValidator(1024)], help_text='Largest accepted file, bytes'
    )
    ssh_enabled = models.BooleanField(default=False, help_text='Accept SCP and SFTP uploads')
    ssh_port = models.PositiveIntegerField(default=DEFAULT_SSH_PORT, validators=PORT_VALIDATORS)
    ssh_username = models.CharField(max_length=64, default='devicevault', help_text='Login devices use')
    ssh_secret = EncryptedJSONField(default=dict, blank=True, help_text='{"password": ...} (encrypted at rest)')
    ssh_authorized_keys = models.TextField(blank=True, help_text='Public keys devices may log in with, one per line')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'receiver settings'

    def __str__(self):
        return f'{self.worker.name} settings'

    @property
    def ssh_password(self) -> str:
        return str((self.ssh_secret or {}).get('password') or '')


class PushRejection(models.Model):
    """A push a receiver refused, or the orchestrator discarded. Only the latest ``KEEP`` per receiver are kept."""

    KEEP = 200
    REASON_CHOICES = [(reason, reason.replace('_', ' ')) for reason in REASONS]

    worker = models.ForeignKey('core.Worker', on_delete=models.CASCADE, related_name='push_rejections')
    at = models.DateTimeField(db_index=True)
    source_ip = models.CharField(max_length=64)
    protocol = models.CharField(max_length=16, choices=[(p, p) for p in PROTOCOLS])
    reason = models.CharField(max_length=32, choices=REASON_CHOICES)
    filename = models.CharField(max_length=255, blank=True)
    detail = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-at', '-pk']

    def __str__(self):
        return f'{self.source_ip} {self.reason} ({self.worker.name})'
