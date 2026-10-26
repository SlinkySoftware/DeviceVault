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

from devicevault_protocol.jobs import FAILURE_AUTH, FAILURE_COMMAND, FAILURE_CONNECTION, FAILURE_TIMEOUT

from .base import CollectionLog, CollectorDriver, DriverParams, PermanentError, Target, TransientError

# A rejected command's reply comes first; config lines further down never count.
REJECTION_LINES = 3


class SshParams(DriverParams):
    port: int = Field(22, ge=1, le=65535, description='SSH port')
    strip_volatile: bool = Field(
        True, description='Drop lines that change on every read (timestamps), so unchanged configs compare equal'
    )


class NetmikoDriver(CollectorDriver):
    device_type: ClassVar[str]
    Params = SshParams
    # ``volatile_lines`` (see CollectorDriver) are also dropped here when params.strip_volatile is set.
    # Regexes (re.match, stripped lines) for the device's "bad command" replies; one in the first
    # few lines of a command's output fails the collection with reason ``command``.
    rejected_output: ClassVar[tuple[str, ...]] = ()

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

    def rejected(self, output: str) -> str | None:
        """The line of ``output`` where the device rejected the command, if it did (see ``rejected_output``)."""
        if not self.rejected_output:
            return None
        rejection = re.compile('|'.join(f'(?:{pattern})' for pattern in self.rejected_output))
        head = [line.strip() for line in output.replace('\r\n', '\n').split('\n') if line.strip()]
        return next((line for line in head[:REJECTION_LINES] if rejection.match(line)), None)

    def collect(self, target, credentials, params, *, timeout: int, log: CollectionLog) -> bytes:
        args = self.connect_args(target, credentials, params, timeout)
        where = f'{target.address}:{params.port}'
        outputs = []
        connected = False
        try:
            with ConnectHandler(**args) as connection:
                connected = True
                log.info(f'connected to {where} as {args["username"]}')
                if args['secret']:
                    try:
                        connection.enable()
                    except ValueError as exc:  # Netmiko: the prompt never became privileged
                        raise PermanentError(f'enable mode refused on {target.address}', reason=FAILURE_AUTH) from exc
                for command in self.commands(params):
                    output = connection.send_command(command, read_timeout=timeout)
                    if line := self.rejected(output):
                        raise PermanentError(f'{target.address} rejected "{command}": {line}', reason=FAILURE_COMMAND)
                    log.info(f'{command}: {len(output)} characters')
                    outputs.append(output)
        except NetmikoAuthenticationException as exc:
            raise PermanentError(
                f'authentication failed for {args["username"]}@{target.address}', reason=FAILURE_AUTH
            ) from exc
        except (TimeoutError, NetmikoTimeoutException, ReadTimeout, SSHException, OSError, EOFError) as exc:
            if connected:  # the session was up: the device stopped answering
                raise TransientError(f'{where} stopped responding: {exc}', reason=FAILURE_TIMEOUT) from exc
            raise TransientError(f'connection to {where} failed: {exc}', reason=FAILURE_CONNECTION) from exc
        return self.clean('\n'.join(outputs), params).encode('utf-8')
