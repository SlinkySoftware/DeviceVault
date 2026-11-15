"""Base for drivers that read configuration from a CLI over SSH, via Netmiko.

A subclass names the Netmiko ``device_type``, the commands that print the
configuration, and optionally how to drop volatile lines (timestamps,
counters) so unchanged configurations compare equal.

Credentials: ``username`` and ``password``, plus ``enable_secret`` for
platforms with a privileged mode.

Host keys are pinned on first use: with ``target.host_key`` set, the device
must present exactly that key, or the collection fails before any credential
is sent. Without one (the device's first backup) any key is accepted and
reported in ``log.host_key`` for the orchestrator to pin.
"""

import contextlib
import os
import re
import tempfile
from collections.abc import Iterator
from typing import Any, ClassVar

from netmiko import ConnectHandler, NetmikoAuthenticationException, NetmikoTimeoutException
from netmiko.exceptions import ReadTimeout
from paramiko.hostkeys import InvalidHostKey
from paramiko.ssh_exception import BadHostKeyException, SSHException
from pydantic import Field

from devicevault_protocol.jobs import FAILURE_AUTH, FAILURE_COMMAND, FAILURE_CONNECTION, FAILURE_TIMEOUT

from .base import CollectionLog, CollectorDriver, DriverParams, PermanentError, Target, TransientError

# A rejected command's reply comes first; config lines further down never count.
REJECTION_LINES = 3


def known_hosts_name(address: str, port: int) -> str:
    """How known_hosts (and Paramiko's lookup) names a server: bare on port 22, else ``[address]:port``."""
    return address if port == 22 else f'[{address}]:{port}'


@contextlib.contextmanager
def pinned_known_hosts(address: str, port: int, host_key: str) -> Iterator[str]:
    """A temporary known_hosts file holding only the device's pinned key."""
    handle, path = tempfile.mkstemp(prefix='known-hosts-')
    try:
        with os.fdopen(handle, 'w', encoding='ascii') as out:
            out.write(f'{known_hosts_name(address, port)} {host_key}\n')
        yield path
    finally:
        os.unlink(path)


def presented_host_key(connection) -> str:
    """The host key of an open Netmiko connection as ``<type> <base64>``, or '' if it cannot be read."""
    try:
        key = connection.remote_conn_pre.get_transport().get_remote_server_key()
        return f'{key.get_name()} {key.get_base64()}'
    except AttributeError, SSHException:
        return ''


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
            # Host keys are pinned per device (see ``collect``): never the worker's own known_hosts.
            'ssh_strict': bool(target.host_key),
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
            with contextlib.ExitStack() as stack:
                if target.host_key:
                    # Paramiko then asks for the pinned key's type and refuses any other key.
                    known_hosts = stack.enter_context(pinned_known_hosts(target.address, params.port, target.host_key))
                    args.update(alt_host_keys=True, alt_key_file=known_hosts)
                connection = stack.enter_context(ConnectHandler(**args))
                connected = True
                log.host_key = presented_host_key(connection)
                log.info(f'connected to {where} as {args["username"]}')
                if not target.host_key and log.host_key:
                    log.warning(f'first connection: accepted host key {log.host_key.split()[0]}, to be pinned')
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
        except InvalidHostKey as exc:
            raise PermanentError(
                f'the host key pinned for {where} is unusable; forget it and back the device up again',
                reason=FAILURE_AUTH,
            ) from exc
        except (TimeoutError, NetmikoTimeoutException, ReadTimeout, SSHException, OSError, EOFError) as exc:
            if connected:  # the session was up: the device stopped answering
                raise TransientError(f'{where} stopped responding: {exc}', reason=FAILURE_TIMEOUT) from exc
            if target.host_key and _host_key_refused(exc):
                raise PermanentError(
                    f'{where} did not present its pinned SSH host key ({target.host_key.split()[0]}), so nothing was '
                    'sent to it. If the device was replaced or re-keyed, forget its host key and back it up again',
                    reason=FAILURE_AUTH,
                ) from exc
            raise TransientError(f'connection to {where} failed: {exc}', reason=FAILURE_CONNECTION) from exc
        return self.clean('\n'.join(outputs), params).encode('utf-8')


def _host_key_refused(exc: BaseException | None) -> bool:
    """Whether Paramiko refused the server's host key: another key, or (RejectPolicy) one of a type not pinned.

    Netmiko re-raises Paramiko's error as its own timeout exception, so the original is found in the chain.
    """
    while exc is not None:
        if isinstance(exc, BadHostKeyException):
            return True
        if isinstance(exc, SSHException) and 'not found in known_hosts' in str(exc):
            return True
        exc = exc.__cause__ or exc.__context__
    return False
