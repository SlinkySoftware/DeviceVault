"""Base for drivers that read configuration from a CLI over SSH, via Netmiko.

A subclass names the Netmiko ``device_type``, the commands that print the
configuration, and optionally how to drop volatile lines (timestamps,
counters) so unchanged configurations compare equal.

Credentials: ``username`` and ``password``, plus ``enable_secret`` for
platforms with a privileged mode.
"""

import re
from typing import Any, ClassVar

from netmiko import ConnectHandler, NetmikoAuthenticationException, NetmikoTimeoutException
from netmiko.exceptions import ReadTimeout
from paramiko.ssh_exception import SSHException
from pydantic import Field

from .base import CollectionLog, CollectorDriver, DriverParams, PermanentError, Target, TransientError


class SshParams(DriverParams):
    port: int = Field(22, ge=1, le=65535, description='SSH port')
    strip_volatile: bool = Field(
        True, description='Drop lines that change on every read (timestamps), so unchanged configs compare equal'
    )


class NetmikoDriver(CollectorDriver):
    device_type: ClassVar[str]
    Params = SshParams
    # ``volatile_lines`` (see CollectorDriver) are also dropped here when params.strip_volatile is set.

    def commands(self, params: SshParams) -> list[str]:
        raise NotImplementedError

    def clean(self, output: str, params: SshParams) -> str:
        lines = output.replace('\r\n', '\n').split('\n')
        if params.strip_volatile and self.volatile_lines:
            volatile = re.compile('|'.join(f'(?:{pattern})' for pattern in self.volatile_lines))
            lines = [line for line in lines if not volatile.match(line.lstrip())]
        return '\n'.join(lines).strip('\n') + '\n'

    def connect_args(self, target: Target, credentials: dict[str, Any], params: SshParams, timeout: int):
        username, password = self.require(credentials, 'username', 'password')
        return {
            'device_type': self.device_type,
            'host': target.address,
            'port': params.port,
            'username': username,
            'password': password,
            'secret': str(credentials.get('enable_secret') or ''),
            'conn_timeout': timeout,
            'auth_timeout': timeout,
            'banner_timeout': timeout,
            # TODO(host keys): pin device host keys instead of accepting any.
            'ssh_strict': False,
            'system_host_keys': False,
            'use_keys': False,
            'allow_agent': False,
        }

    def collect(self, target, credentials, params, *, timeout: int, log: CollectionLog) -> bytes:
        args = self.connect_args(target, credentials, params, timeout)
        outputs = []
        try:
            with ConnectHandler(**args) as connection:
                log.info(f'connected to {target.address}:{params.port} as {args["username"]}')
                if args['secret']:
                    connection.enable()
                for command in self.commands(params):
                    output = connection.send_command(command, read_timeout=timeout)
                    log.info(f'{command}: {len(output)} characters')
                    outputs.append(output)
        except NetmikoAuthenticationException as exc:
            raise PermanentError(f'authentication failed for {args["username"]}@{target.address}') from exc
        except (TimeoutError, NetmikoTimeoutException, ReadTimeout, SSHException, OSError, EOFError) as exc:
            raise TransientError(f'connection to {target.address}:{params.port} failed: {exc}') from exc
        return self.clean('\n'.join(outputs), params).encode('utf-8')
