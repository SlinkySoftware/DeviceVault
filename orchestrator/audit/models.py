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

"""
Audit Logging Model
Tracks all user actions and changes for compliance, security, and debugging.
"""

from django.db import models
from django.contrib.auth.models import User


class AuditLog(models.Model):
    """
    AuditLog Model: Records all user actions and changes in the system
    
    Fields:
        - created_at (DateTimeField): When the action occurred
        - actor (ForeignKey): User who performed the action
        - action (CharField): Action type (create, update, delete, login, etc.)
        - resource (CharField): Resource affected (Device, Backup, Schedule, etc.)
        - details (JSONField): Additional context data about the change
        - label_scope (JSONField): Labels related to the resource (for audit filtering)
    
    Usage:
        Every significant action is logged for:
        - Compliance reporting
        - Security auditing
        - Debugging issues
        - Tracking who made what changes and when
    
    Action Examples:
        - create_device: New device was created
        - update_device: Device was modified
        - delete_device: Device was removed
        - execute_backup: Backup job ran
        - toggle_schedule: Schedule was enabled/disabled
    """
    created_at = models.DateTimeField(auto_now_add=True, help_text='Timestamp of when action occurred')
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, help_text='User who performed the action')
    action = models.CharField(max_length=128, help_text='Type of action (create, update, delete, etc.)')
    resource = models.CharField(max_length=128, help_text='Type of resource affected (Device, Backup, etc.)')
    details = models.JSONField(default=dict, help_text='Additional context: changed fields, old/new values, etc.')
    label_scope = models.JSONField(default=list, help_text='Labels of affected resource for access control filtering')
