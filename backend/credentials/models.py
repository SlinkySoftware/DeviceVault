"""
Credential Management Models
Handles authentication credentials for device access including SSH, Telnet,
and external credential management system integrations (CyberArk, HashiCorp Vault, etc.).
"""

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
