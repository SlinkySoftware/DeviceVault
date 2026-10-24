"""The SCP/SFTP listener (asyncssh).

One SSH server accepts both: SCP runs through the SFTP server's file methods,
so ``UploadServer`` is the only place uploads are handled. It is write-only:
files can be created and written, nothing can be read, listed, renamed or
removed, and there is no shell, exec or port forwarding.

A connection is accepted only from a push-enabled device (by source address)
that pushes over SSH, with the receiver's username and password or one of its
authorised keys. Each file is spooled under the connection's own directory,
checked against the device's filename pattern and the size limit, and handed
to the receiver to stage when the client closes it; the client sees the close
fail if staging fails.
"""

import fnmatch
import hmac
import os
import posixpath
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO

import asyncssh
from asyncssh import FXF_READ, FXF_WRITE, SFTPAttrs, SFTPFailure, SFTPOpUnsupported, SFTPPermissionDenied

from devicevault_protocol.logs import get_logger
from devicevault_protocol.push import (
    PUSH_SSH,
    REASON_AUTH_FAILED,
    REASON_ERROR,
    REASON_FILENAME,
    REASON_TOO_LARGE,
    REASON_UNKNOWN_SOURCE,
    REASON_WRONG_PROTOCOL,
    normalise_address,
)

if TYPE_CHECKING:
    from .receiver import Receiver

logger = get_logger('devicevault.receiver.ssh')


class SshListener:
    """Starts, stops and restarts the SSH server as the assignment changes."""

    def __init__(self, receiver: Receiver):
        self.receiver = receiver
        self._server: asyncssh.SSHAcceptor | None = None
        self.bound: tuple[str, int] | None = None
        self.error = ''

    def status(self) -> dict:
        config = self.receiver.config.ssh
        return {
            'enabled': config.enabled,
            'port': config.port,
            'listening': self.bound is not None,
            'error': self.error,
        }

    async def configure(self) -> None:
        config = self.receiver.config
        wanted = (config.bind_address, config.ssh.port) if config.ssh.enabled else None
        if wanted == self.bound and (wanted is None or self._server is not None):
            return
        await self.stop()
        if wanted is None:
            return
        try:
            self._server = await asyncssh.create_server(
                lambda: Connection(self.receiver),
                host=config.bind_address or None,
                port=config.ssh.port,
                server_host_keys=[self.receiver.host_key],
                sftp_factory=lambda channel: UploadServer(channel, self.receiver),
                allow_scp=True,
                agent_forwarding=False,
                allow_pty=False,
                x11_forwarding=False,
                login_timeout=60,
                keepalive_interval=30,
            )
        except OSError as exc:
            self.error = f'cannot listen on {config.bind_address or "*"}:{config.ssh.port}: {exc.strerror or exc}'
            logger.error('ssh_listen_failed', extra={'port': config.ssh.port, 'error': self.error})
            return
        self.bound = wanted
        self.error = ''
        logger.info('ssh_listening', extra={'address': config.bind_address or '*', 'port': config.ssh.port})

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            logger.info('ssh_stopped', extra={'port': self.bound[1] if self.bound else None})
        self._server = None
        self.bound = None


class Connection(asyncssh.SSHServer):
    """One client connection: who it is and whether it may log in."""

    def __init__(self, receiver: Receiver):
        self.receiver = receiver
        self.source = ''
        self._conn: asyncssh.SSHServerConnection | None = None

    def connection_made(self, conn: asyncssh.SSHServerConnection) -> None:
        self._conn = conn
        peer = conn.get_extra_info('peername') or ('',)
        try:
            self.source = normalise_address(str(peer[0]))
        except ValueError:
            self.source = str(peer[0])

    def _rejected(self, reason: str, detail: str = '', filename: str = '') -> None:
        self.receiver.events.rejected(
            source_ip=self.source, protocol=PUSH_SSH, reason=reason, filename=filename, detail=detail
        )

    def device(self):
        """The device at the source address, if it may push here over SSH."""
        device = self.receiver.config.device_for(self.source)
        return device if device is not None and device.push_mode == PUSH_SSH else None

    def begin_auth(self, username: str) -> bool:
        device = self.receiver.config.device_for(self.source)
        if device is None:
            self._rejected(REASON_UNKNOWN_SOURCE, 'no push-enabled device has this address')
        elif device.push_mode != PUSH_SSH:
            self._rejected(REASON_WRONG_PROTOCOL, f'the device pushes over {device.push_mode}')
        elif self.receiver.authorized_keys is not None and _same(username, self.receiver.config.ssh.username):
            self._conn.set_authorized_keys(self.receiver.authorized_keys)
        return True  # everyone must authenticate; failures are decided below

    def password_auth_supported(self) -> bool:
        return True

    def validate_password(self, username: str, password: str) -> bool:
        if self.device() is None:
            return False
        ssh = self.receiver.config.ssh
        if ssh.password and _same(username, ssh.username) and _same(password, ssh.password):
            return True
        self._rejected(REASON_AUTH_FAILED, f'wrong username or password for "{username[:64]}"')
        return False

    def public_key_auth_supported(self) -> bool:
        return True

    def auth_completed(self) -> None:
        logger.info('ssh_login', extra={'source_ip': self.source})


def _same(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


@dataclass
class Upload:
    """An SFTP file handle: one file being uploaded."""

    handle: BinaryIO
    path: Path
    filename: str
    size: int = 0
    refused: bool = False


class UploadServer(asyncssh.SFTPServer):
    """A write-only SFTP server (also serving SCP) rooted in a per-connection spool directory."""

    def __init__(self, channel: asyncssh.SSHServerChannel, receiver: Receiver):
        self.receiver = receiver
        self.client: Connection = channel.get_connection().get_owner()
        self.root = Path(tempfile.mkdtemp(prefix='ssh-', dir=receiver.spool_dir))
        super().__init__(channel, chroot=os.fsencode(self.root))

    def exit(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)
        # OpenSSH's scp (SFTP mode) fails unless the session reports an exit status,
        # as OpenSSH's sftp-server does; asyncssh just closes the channel.
        try:
            self.channel.exit(0)
        except OSError, asyncssh.Error:
            pass  # the client already went away

    # --- uploads ------------------------------------------------------------------

    def open(self, path: bytes, pflags: int, attrs: SFTPAttrs) -> Upload:
        if pflags & FXF_READ or not pflags & FXF_WRITE:
            raise SFTPPermissionDenied('this server only accepts uploads')
        device = self.client.device()
        if device is None:  # the device was removed or changed since the client logged in
            raise SFTPPermissionDenied('this device may no longer push here')
        filename = posixpath.basename(path.decode('utf-8', 'replace').rstrip('/'))
        if not filename or filename in ('.', '..'):
            raise SFTPFailure('a file name is required')
        if device.filename_pattern and not fnmatch.fnmatchcase(filename, device.filename_pattern):
            self.client._rejected(REASON_FILENAME, f'does not match {device.filename_pattern}', filename)
            raise SFTPPermissionDenied(f'file names must match {device.filename_pattern}')
        local = self.root / uuid.uuid4().hex
        return Upload(handle=open(local, 'w+b'), path=local, filename=filename)

    def write(self, file_obj: Upload, offset: int, data: bytes) -> int:
        limit = self.receiver.config.max_file_size
        if file_obj.refused or offset + len(data) > limit:
            if not file_obj.refused:
                file_obj.refused = True
                self.client._rejected(REASON_TOO_LARGE, f'larger than {limit} bytes', file_obj.filename)
            raise SFTPFailure(f'files may be at most {limit} bytes')
        file_obj.handle.seek(offset)
        file_obj.handle.write(data)
        file_obj.size = max(file_obj.size, offset + len(data))
        return len(data)

    async def close(self, file_obj: Upload) -> None:
        file_obj.handle.close()
        try:
            if file_obj.refused:
                return
            device = self.client.device()
            if device is None:
                raise SFTPPermissionDenied('this device may no longer push here')
            try:
                await self.receiver.ingest(
                    device=device,
                    source_ip=self.client.source,
                    protocol=PUSH_SSH,
                    filename=file_obj.filename,
                    path=file_obj.path,
                )
            except Exception as exc:
                logger.exception('ssh_ingest_failed', extra={'file': file_obj.filename})
                self.client._rejected(REASON_ERROR, f'could not stage the backup: {exc}', file_obj.filename)
                raise SFTPFailure('the backup could not be stored, try again later') from exc
        finally:
            file_obj.path.unlink(missing_ok=True)

    def fstat(self, file_obj: Upload) -> SFTPAttrs:
        return SFTPAttrs(size=file_obj.size, permissions=0o100600)

    def fsetstat(self, file_obj: Upload, attrs: SFTPAttrs) -> None:
        pass  # times and modes (scp -p) mean nothing here

    def setstat(self, path: bytes, attrs: SFTPAttrs) -> None:
        pass

    def fsync(self, file_obj: Upload) -> None:
        pass

    # --- everything else is refused ------------------------------------------------

    def read(self, file_obj: object, offset: int, size: int) -> bytes:
        raise SFTPPermissionDenied('this server only accepts uploads')

    async def scandir(self, path: bytes):
        raise SFTPPermissionDenied('listing is not allowed')
        yield  # an async generator, as asyncssh expects

    def _refuse(self, *_args) -> None:
        raise SFTPPermissionDenied('this server only accepts uploads')

    remove = rename = posix_rename = mkdir = rmdir = symlink = link = _refuse

    def readlink(self, path: bytes) -> bytes:
        raise SFTPOpUnsupported('links are not supported')
