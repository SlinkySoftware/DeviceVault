"""
Credential Management Models
Handles authentication credentials for device access including SSH, Telnet,
and external credential management system integrations (CyberArk, HashiCorp Vault, etc.).
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

from django.db import models


class CredentialType(models.Model):
    """
    CredentialType Model: Defines supported credential management sources
    
    Fields:
        - name (CharField): Type name (e.g., "Local", "CyberArk", "HashiCorp Vault")
    
    Methods:
        - __str__(): Returns the credential type name
    
    Usage:
        Credential types define where credentials are sourced from:
        - Local: Stored in database (for testing/demo)
        - CyberArk: Enterprise password vault
        - HashiCorp Vault: Open-source secret management
        - Azure Key Vault: Cloud-based secret store
    """
    name = models.CharField(max_length=64, unique=True, help_text='Credential source type')
    
    def __str__(self):
        """Return credential type name for admin display"""
        return self.name


class Credential(models.Model):
    """
    Credential Model: Stores or references authentication credentials for device access
    
    Fields:
        - name (CharField): Display name for credential set
        - credential_type (ForeignKey): Type of credential source
        - data (JSONField): Credential data as JSON (username/password, API keys, config, etc.)
    
    Methods:
        - __str__(): Returns the credential name
    
    Usage:
        Credentials are associated with devices to provide access to backup/restore operations.
        For local credentials, data contains {'username': 'admin', 'password': 'secret'}.
        For external vaults, data contains connection parameters (URL, API key, path, etc.).
    """
    name = models.CharField(max_length=128, help_text='Display name for this credential set')
    credential_type = models.ForeignKey(CredentialType, on_delete=models.PROTECT, help_text='Source of credentials')
    data = models.JSONField(default=dict, help_text='Credential data: username/password dict or vault connection params')
    
    def __str__(self):
        """Return credential name for admin display"""
        return self.name
