"""
Copyright (C) 2026, Slinky Software

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.
"""

"""Audit log: who did what, from where, and whether it was allowed."""

from django.contrib.auth.models import User
from django.db import models


class AuditLog(models.Model):
    """One recorded action. Written through ``audit.log.record``.

    ``actor_name`` is a snapshot, so failed sign-ins by unknown names and the
    actions of deleted users stay readable. ``device_group`` is set for actions
    on a device group's devices and backups.
    """

    SUCCESS = 'success'
    FAILURE = 'failure'
    DENIED = 'denied'
    OUTCOME_CHOICES = [(SUCCESS, 'Success'), (FAILURE, 'Failure'), (DENIED, 'Denied')]

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    actor_name = models.CharField(max_length=150, blank=True)
    action = models.CharField(max_length=128, db_index=True, help_text='e.g. auth.login, user.update, backup.view')
    resource = models.CharField(max_length=128, blank=True, help_text='What was acted on, e.g. a user or backup id')
    outcome = models.CharField(max_length=16, choices=OUTCOME_CHOICES, default=SUCCESS)
    details = models.JSONField(default=dict, blank=True, help_text='Context, such as before and after values')
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)
    device_group = models.ForeignKey(
        'devices.DeviceGroup', on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f'{self.created_at:%Y-%m-%d %H:%M:%S} {self.actor_name or "-"} {self.action} {self.outcome}'
