"""
Core Application Models
Defines user preferences and dashboard layout configuration.
"""

# DeviceVault - A comprehensive network device backup management application with web interface for user and admin access and backend component for automated backup collection.
# Copyright (C) 2026, Slinky Software
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import uuid

from django.contrib.auth.models import User
from django.db import models

from devicevault_protocol.names import collection_queue_name
from devicevault_protocol.registration import (
    ROLE_COLLECTOR,
    ROLE_STORAGE,
    STATUS_APPROVED,
    STATUS_PENDING,
    STATUS_REVOKED,
)


class UserProfile(models.Model):
    """
    UserProfile Model: Stores user-specific preferences and settings

    Fields:
        - user (OneToOneField): Link to Django User account
        - theme (CharField): UI theme preference (light or dark)
        - created_at (DateTimeField): When profile was created
        - updated_at (DateTimeField): When profile was last modified

    Methods:
        - __str__(): Returns descriptive string with username

    Theme Options:
        - light: Light mode UI
        - dark: Dark mode UI (default)

    Usage:
        Each user has one associated profile containing their preferences.
        Profile is created automatically when user logs in if it doesn't exist.
    """

    THEME_CHOICES = [
        ('light', 'Light Mode'),
        ('dark', 'Dark Mode'),
    ]

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name='profile', help_text='Associated user account'
    )
    theme = models.CharField(max_length=10, choices=THEME_CHOICES, default='dark', help_text='UI theme preference')
    created_at = models.DateTimeField(auto_now_add=True, help_text='Profile creation timestamp')
    updated_at = models.DateTimeField(auto_now=True, help_text='Last modification timestamp')

    def __str__(self):
        """Return profile description with username"""
        return f'Profile for {self.user.username}'


class DashboardLayout(models.Model):
    """
    DashboardLayout Model: Stores dashboard widget configuration per user or as default

    Fields:
        - user (OneToOneField): User who owns this layout (null for default layout)
        - is_default (BooleanField): Whether this is the default layout for new users
        - layout (JSONField): Array of widget configuration objects
        - created_at (DateTimeField): When layout was created
        - updated_at (DateTimeField): When layout was last modified

    Methods:
        - __str__(): Returns descriptive string

    Layout Structure:
        layout is a JSON array of widget objects, each containing:
        - type: Widget type (stats, chart, table, etc.)
        - position: Grid position {row, col}
        - size: Widget dimensions {width, height}
        - config: Widget-specific configuration

    Usage:
        Each user can customize their dashboard layout.
        A default layout is provided for new users and can be customized by admins.
        Users can have only one layout, and either it's personal or the default.
    """

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='dashboard_layout',
        null=True,
        blank=True,
        help_text='User who customized this layout (null for default)',
    )
    is_default = models.BooleanField(default=False, help_text='Whether this is the default layout for all users')
    layout = models.JSONField(default=list, help_text='Dashboard widget configuration as JSON array')
    created_at = models.DateTimeField(auto_now_add=True, help_text='Layout creation timestamp')
    updated_at = models.DateTimeField(auto_now=True, help_text='Last modification timestamp')

    class Meta:
        unique_together = [['user', 'is_default']]

    def __str__(self):
        """Return descriptive string with user or default indicator"""
        if self.is_default:
            return 'Default Dashboard Layout'
        return f'Dashboard Layout for {self.user.username}'


class Worker(models.Model):
    """A collection or storage worker that has registered with the orchestrator.

    Workers register themselves (status ``pending``). An administrator approves
    one with a role and an assignment (collection groups or storage targets);
    the orchestrator then pushes a signed assignment, and the worker reports
    which version it has applied in every heartbeat.
    """

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending approval'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_REVOKED, 'Revoked'),
    ]
    ROLE_CHOICES = [('', 'Unassigned'), (ROLE_COLLECTOR, 'Collector'), (ROLE_STORAGE, 'Storage')]

    id = models.UUIDField(primary_key=True, help_text='Worker id, generated by the worker on first start')
    name = models.CharField(max_length=255)
    celery_hostname = models.CharField(max_length=255, blank=True, help_text='Celery node name (name@host)')
    hostname = models.CharField(max_length=255, blank=True)
    pid = models.IntegerField(null=True, blank=True)
    version = models.CharField(max_length=64, blank=True)

    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    role = models.CharField(max_length=16, choices=ROLE_CHOICES, blank=True, default='')
    collection_groups = models.ManyToManyField('devices.CollectionGroup', blank=True, related_name='workers')

    signing_key = models.CharField(max_length=64, help_text='Ed25519 public key (base64), fixed at registration')
    encryption_key = models.CharField(max_length=64, help_text='X25519 public key (base64)')
    fingerprint = models.CharField(max_length=64)
    pinned_orchestrator_key = models.CharField(
        max_length=64, blank=True, help_text='Orchestrator key the worker reports having pinned'
    )
    capabilities = models.JSONField(default=dict, blank=True)

    desired_version = models.PositiveIntegerField(default=0, help_text='Version of the current assignment')
    applied_version = models.PositiveIntegerField(default=0, help_text='Assignment version the worker reports')
    applied_queues = models.JSONField(default=list, blank=True)

    registered_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['status', 'name']

    def __str__(self):
        return f'{self.name} [{self.status}]'

    def assigned_queues(self) -> list[str]:
        """Queues this worker should consume under its current assignment."""
        if self.status != STATUS_APPROVED:
            return []
        if self.role == ROLE_COLLECTOR:
            return sorted(collection_queue_name(g.rabbitmq_queue_id) for g in self.collection_groups.all())
        if self.role == ROLE_STORAGE:
            return sorted(target.queue for target in self.storage_targets.all())
        return []


class Installation(models.Model):
    """This database's identity: one row, created on first use (see core.installation)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
