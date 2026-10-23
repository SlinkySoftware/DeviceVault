"""MikroTik RouterOS: ``/export`` over SSH."""

import paramiko
from pydantic import Field

from .base import CollectorDriver, DriverParams, PermanentError, TransientError


class MikrotikExportParams(DriverParams):
    port: int = Field(22, ge=1, le=65535, description='SSH port')
    show_sensitive: bool = Field(True, description='Include secrets in the export (show-sensitive)')


class MikrotikExportDriver(CollectorDriver):
    key = 'mikrotik_ssh_export'
    name = 'MikroTik SSH Export'
    description = 'Runs /export over SSH on RouterOS to capture the full configuration.'
    version = '2'
    Params = MikrotikExportParams

    def collect(self, target, credentials, params, *, timeout, log):
        username, password = self.require(credentials, 'username', 'password')
        command = '/export show-sensitive' if params.show_sensitive else '/export'
        client = paramiko.SSHClient()
        # TODO(host keys): pin device host keys instead of accepting any.
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                hostname=target.address,
                port=params.port,
                username=username,
                password=password,
                look_for_keys=False,
                allow_agent=False,
                timeout=timeout,
                banner_timeout=timeout,
                auth_timeout=timeout,
            )
            log.info(f'connected to {target.address}:{params.port} as {username}')
            _, stdout, stderr = client.exec_command(command, timeout=timeout)
            output = stdout.read()
            errors = stderr.read().decode('utf-8', errors='replace').strip()
        except paramiko.AuthenticationException as exc:
            raise PermanentError(f'authentication failed: {exc}') from exc
        except (TimeoutError, ConnectionError, OSError, paramiko.SSHException) as exc:
            raise TransientError(f'connection to {target.address}:{params.port} failed: {exc}') from exc
        finally:
            client.close()
        if errors:
            raise PermanentError(f'{command} failed: {errors}')
        log.info(f'{command} returned {len(output)} bytes')
        return output
