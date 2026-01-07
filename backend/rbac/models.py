"""
Role-Based Access Control Models
Implements user roles, permissions, and label-based access control for multi-tenant scenarios.
"""

from django.db import models
from django.contrib.auth.models import User
from core.models import Label


class Permission(models.Model):
    """
    Permission Model: Granular actions users can perform
    
    Fields:
        - code (CharField): Unique permission identifier (e.g., "view_devices", "edit_credentials")
        - description (TextField): Human-readable explanation
    
    Methods:
        - __str__(): Returns the permission code
    
    Permission Examples:
        - view_devices: Can view device list
        - edit_devices: Can create and modify devices
        - delete_devices: Can delete devices
        - manage_credentials: Can view and edit credentials
        - admin_access: Full administrative access
    
    Usage:
        Permissions are assigned to roles, which are assigned to users.
        Granular control allows precise access management.
    """
    code = models.CharField(max_length=128, unique=True, help_text='Unique permission identifier')
    description = models.TextField(blank=True, help_text='Description of what this permission allows')
    
    def __str__(self):
        """Return permission code for admin display"""
        return self.code


class Role(models.Model):
    """
    Role Model: Groups permissions and label scopes for access control
    
    Fields:
        - name (CharField): Unique role name (e.g., "Administrator", "Operator")
        - permissions (ManyToManyField): Permissions assigned to this role
        - labels (ManyToManyField): Labels this role can access (multi-tenancy support)
    
    Methods:
        - __str__(): Returns the role name
    
    Role Examples:
        - Administrator: All permissions, all labels
        - Operator: View/manage devices and backups, limited to assigned labels
        - Viewer: Read-only access to devices and backups
    
    Usage:
        Roles bundle permissions and label scopes together.
        Users are assigned roles to determine what they can do and what data they can access.
    """
    name = models.CharField(max_length=64, unique=True, help_text='Unique role name')
    permissions = models.ManyToManyField(Permission, blank=True, help_text='Permissions granted to users with this role')
    labels = models.ManyToManyField(Label, blank=True, help_text='Labels/environments this role can access')
    
    def __str__(self):
        """Return role name for admin display"""
        return self.name


class UserRole(models.Model):
    """
    UserRole Model: Associates users with roles
    
    Fields:
        - user (ForeignKey): User being assigned a role
        - role (ForeignKey): Role to assign to user
    
    Constraints:
        - Each user-role pair is unique (no duplicate assignments)
    
    Usage:
        Users can have multiple roles. Each role grants permissions and label scopes.
        When checking access, all user's roles are evaluated to determine final permissions.
    
    Examples:
        - User "john" has role "Administrator" → full access
        - User "jane" has roles "Operator" (Production), "Operator" (Development) 
          → can manage devices in both environments
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, help_text='User being assigned a role')
    role = models.ForeignKey(Role, on_delete=models.CASCADE, help_text='Role to assign')
    
    class Meta:
        unique_together = ('user', 'role')
