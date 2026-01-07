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
