"""The TFTP listener: write requests only (RFC 1350, options per RFC 2347-2349).

TFTP has no authentication, and its UDP source addresses can be forged, so it
is a per-device opt-in: a write request is accepted only from the address of
a device set to push over TFTP, with a file name matching its pattern. Read
requests are refused.

Each accepted request gets its own socket (a new transfer id, as the RFC
requires) and task. Blocks are acknowledged one at a time; block numbers wrap
after 65535 so large files work with the default 512-byte blocks. The final
block is acknowledged only once the file is staged, so a device whose upload
could not be stored gets an error rather than a success.
"""

import asyncio
import errno
import fnmatch
import socket
import struct
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, BinaryIO

from devicevault_protocol.logs import get_logger
from devicevault_protocol.push import (
    PUSH_TFTP,
    REASON_ERROR,
    REASON_FILENAME,
    REASON_TOO_LARGE,
    REASON_UNKNOWN_SOURCE,
    REASON_WRONG_PROTOCOL,
    normalise_address,
)

from .config import Device

if TYPE_CHECKING:
    from .receiver import Receiver

logger = get_logger('devicevault.receiver.tftp')

RRQ, WRQ, DATA, ACK, ERROR, OACK = range(1, 7)

ERR_UNDEFINED = 0
ERR_ACCESS_VIOLATION = 2
ERR_DISK_FULL = 3
ERR_ILLEGAL_OPERATION = 4
ERR_UNKNOWN_TID = 5

DEFAULT_BLKSIZE = 512
MAX_BLKSIZE = 65464  # RFC 2348
DEFAULT_TIMEOUT = 5
MAX_RETRIES = 5
MAX_TRANSFERS = 64


# --- packets --------------------------------------------------------------------------------


def ack(block: int) -> bytes:
    return struct.pack('!HH', ACK, block)


def error(code: int, message: str) -> bytes:
    return struct.pack('!HH', ERROR, code) + message.encode('ascii', 'replace') + b'\0'


def oack(options: dict[str, str]) -> bytes:
    return struct.pack('!H', OACK) + b''.join(f'{k}\0{v}\0'.encode('ascii') for k, v in options.items())


def data(block: int, payload: bytes) -> bytes:
    return struct.pack('!HH', DATA, block) + payload


class Malformed(ValueError):
    pass


@dataclass(frozen=True)
class Request:
    opcode: int
    filename: str
    mode: str
    options: dict[str, str]


def parse_request(packet: bytes) -> Request:
    """A read or write request: ``opcode filename\\0 mode\\0 [option\\0 value\\0]...``."""
    if len(packet) < 4:
        raise Malformed('short request')
    opcode = struct.unpack('!H', packet[:2])[0]
    fields = packet[2:].split(b'\0')
    if fields[-1] != b'' or len(fields) < 3:
        raise Malformed('request is not NUL-terminated')
    fields = [f.decode('ascii', 'replace') for f in fields[:-1]]
    filename, mode, rest = fields[0], fields[1].lower(), fields[2:]
    if len(rest) % 2:
        rest = rest[:-1]  # a dangling option name; ignore it
    options = {rest[i].lower(): rest[i + 1] for i in range(0, len(rest), 2)}
    return Request(opcode=opcode, filename=filename, mode=mode, options=options)


def negotiate(options: dict[str, str]) -> tuple[dict[str, str], int, int]:
    """The options to acknowledge, the block size and the timeout. Unknown or bad options are ignored."""
    accepted: dict[str, str] = {}
    blksize, timeout = DEFAULT_BLKSIZE, DEFAULT_TIMEOUT
    if (value := options.get('blksize', '')).isdigit() and int(value) >= 8:
        blksize = min(int(value), MAX_BLKSIZE)
        accepted['blksize'] = str(blksize)
    if (value := options.get('timeout', '')).isdigit() and 1 <= int(value) <= 255:
        timeout = int(value)
        accepted['timeout'] = value
    if options.get('tsize', '').isdigit():
        accepted['tsize'] = options['tsize']
    return accepted, blksize, timeout


class NetasciiDecoder:
    """netascii (CR LF for newlines, CR NUL for a bare CR) back to the device's bytes."""

    def __init__(self):
        self._carry = b''

    def decode(self, chunk: bytes, final: bool = False) -> bytes:
        text = self._carry + chunk
        self._carry = b''
        if not final and text.endswith(b'\r'):
            text, self._carry = text[:-1], b'\r'
        return text.replace(b'\r\n', b'\n').replace(b'\r\0', b'\r')


# --- listener ---------------------------------------------------------------------------------


class _Datagrams(asyncio.DatagramProtocol):
    def __init__(self, on_packet):
        self._on_packet = on_packet

    def datagram_received(self, packet: bytes, addr) -> None:
        self._on_packet(packet, addr)


def _sockets(host: str, port: int) -> list[socket.socket]:
    """Bound UDP sockets: on ``host``, or on every IPv4 and IPv6 address."""
    if host:
        targets = [(socket.AF_INET6 if ':' in host else socket.AF_INET, host)]
    else:
        targets = [(socket.AF_INET, '0.0.0.0'), (socket.AF_INET6, '::')]
    bound: list[socket.socket] = []
    try:
        for family, address in targets:
            try:
                sock = socket.socket(family, socket.SOCK_DGRAM)
            except OSError as exc:
                if not host and family == socket.AF_INET6 and exc.errno == errno.EAFNOSUPPORT:
                    continue  # no IPv6 here
                raise
            try:
                if family == socket.AF_INET6:
                    sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
                sock.bind((address, port))
            except OSError as exc:
                sock.close()
                if not host and family == socket.AF_INET6 and exc.errno == errno.EADDRNOTAVAIL:
                    continue
                raise
            sock.setblocking(False)
            bound.append(sock)
    except OSError:
        for sock in bound:
            sock.close()
        raise
    return bound


class TftpListener:
    """Opens, closes and reopens the TFTP port as the assignment changes, and runs transfers."""

    def __init__(self, receiver: Receiver):
        self.receiver = receiver
        self._transports: list[asyncio.DatagramTransport] = []
        self._transfers: set[asyncio.Task] = set()
        self.bound: tuple[str, int] | None = None
        self.error = ''

    def status(self) -> dict:
        config = self.receiver.config.tftp
        return {
            'enabled': config.enabled,
            'port': config.port,
            'listening': self.bound is not None,
            'error': self.error,
        }

    async def configure(self) -> None:
        config = self.receiver.config
        wanted = (config.bind_address, config.tftp.port) if config.tftp.enabled else None
        if wanted == self.bound and (wanted is None or self._transports):
            return
        await self.stop()
        if wanted is None:
            return
        try:
            sockets = _sockets(config.bind_address, config.tftp.port)
        except OSError as exc:
            self.error = f'cannot listen on {config.bind_address or "*"}:{config.tftp.port}/udp: {exc.strerror or exc}'
            logger.error('tftp_listen_failed', extra={'port': config.tftp.port, 'error': self.error})
            return
        loop = asyncio.get_running_loop()
        for sock in sockets:
            transport, _ = await loop.create_datagram_endpoint(
                lambda sock=sock: _Datagrams(lambda packet, addr: self._request(packet, addr, sock)), sock=sock
            )
            self._transports.append(transport)
        self.bound = wanted
        self.error = ''
        logger.info('tftp_listening', extra={'address': config.bind_address or '*', 'port': config.tftp.port})

    async def stop(self) -> None:
        for transport in self._transports:
            transport.close()
        if self._transports:
            logger.info('tftp_stopped', extra={'port': self.bound[1] if self.bound else None})
        self._transports = []
        self.bound = None
        for task in list(self._transfers):
            task.cancel()
        if self._transfers:
            await asyncio.gather(*self._transfers, return_exceptions=True)

    def _request(self, packet: bytes, addr, sock: socket.socket) -> None:
        def reply(message: bytes) -> None:
            try:
                sock.sendto(message, addr)
            except OSError:
                pass

        try:
            source = normalise_address(str(addr[0]))
        except ValueError:
            return
        try:
            request = parse_request(packet)
        except Malformed:
            reply(error(ERR_ILLEGAL_OPERATION, 'malformed request'))
            return

        def refuse(code: int, message: str, reason: str | None = None, detail: str = '') -> None:
            reply(error(code, message))
            if reason:
                self.receiver.events.rejected(
                    source_ip=source, protocol=PUSH_TFTP, reason=reason, filename=request.filename, detail=detail
                )

        if request.opcode == RRQ:
            refuse(ERR_ACCESS_VIOLATION, 'this server only accepts uploads')
            return
        if request.opcode != WRQ:
            refuse(ERR_ILLEGAL_OPERATION, 'expected a write request')
            return
        config = self.receiver.config
        device = config.device_for(source)
        if device is None:
            refuse(
                ERR_ACCESS_VIOLATION,
                'access violation',
                REASON_UNKNOWN_SOURCE,
                'no push-enabled device has this address',
            )
            return
        if device.push_mode != PUSH_TFTP:
            refuse(
                ERR_ACCESS_VIOLATION,
                'access violation',
                REASON_WRONG_PROTOCOL,
                f'the device pushes over {device.push_mode}',
            )
            return
        filename = request.filename.replace('\\', '/').rstrip('/').rsplit('/', 1)[-1]
        if not filename or filename in ('.', '..'):
            refuse(ERR_ACCESS_VIOLATION, 'a file name is required')
            return
        if device.filename_pattern and not fnmatch.fnmatchcase(filename, device.filename_pattern):
            refuse(
                ERR_ACCESS_VIOLATION,
                f'file names must match {device.filename_pattern}',
                REASON_FILENAME,
                f'does not match {device.filename_pattern}',
            )
            return
        if request.mode not in ('octet', 'netascii'):
            refuse(ERR_ILLEGAL_OPERATION, f'mode {request.mode} is not supported')
            return
        options, blksize, timeout = negotiate(request.options)
        if int(options.get('tsize', 0)) > config.max_file_size:
            refuse(
                ERR_DISK_FULL,
                f'files may be at most {config.max_file_size} bytes',
                REASON_TOO_LARGE,
                f'larger than {config.max_file_size} bytes',
            )
            return
        if len(self._transfers) >= MAX_TRANSFERS:
            refuse(ERR_UNDEFINED, 'too many uploads in progress, try again later')
            return
        transfer = Transfer(
            self.receiver,
            family=sock.family,
            local_host=sock.getsockname()[0],
            peer=addr,
            source_ip=source,
            device=device,
            filename=filename,
            netascii=request.mode == 'netascii',
            options=options,
            blksize=blksize,
            timeout=timeout,
        )
        task = asyncio.get_running_loop().create_task(transfer.run())
        self._transfers.add(task)
        task.add_done_callback(self._transfers.discard)


# --- transfers ----------------------------------------------------------------------------------


class _Queue(asyncio.DatagramProtocol):
    def __init__(self):
        self.packets: asyncio.Queue[tuple[bytes, tuple]] = asyncio.Queue()

    def datagram_received(self, packet: bytes, addr) -> None:
        self.packets.put_nowait((packet, addr))


class TransferFailed(Exception):
    pass


class Transfer:
    """One upload, on its own socket."""

    def __init__(
        self,
        receiver: Receiver,
        *,
        family: int,
        local_host: str,
        peer: tuple,
        source_ip: str,
        device: Device,
        filename: str,
        netascii: bool,
        options: dict[str, str],
        blksize: int,
        timeout: int,
    ):
        self.receiver = receiver
        self.family = family
        self.local_host = local_host
        self.peer = peer
        self.source_ip = source_ip
        self.device = device
        self.filename = filename
        self.netascii = netascii
        self.options = options
        self.blksize = blksize
        self.timeout = timeout
        self.path = receiver.spool_dir / f'tftp-{uuid.uuid4().hex}'

    def _rejected(self, reason: str, detail: str) -> None:
        self.receiver.events.rejected(
            source_ip=self.source_ip, protocol=PUSH_TFTP, reason=reason, filename=self.filename, detail=detail
        )

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        transport, protocol = await loop.create_datagram_endpoint(
            _Queue, local_addr=(self.local_host, 0), family=self.family
        )
        try:
            await self._transfer(transport, protocol.packets)
        except TransferFailed as exc:
            logger.warning(
                'tftp_transfer_failed', extra={'source_ip': self.source_ip, 'file': self.filename, 'error': str(exc)}
            )
        except asyncio.CancelledError:
            transport.sendto(error(ERR_UNDEFINED, 'the receiver is shutting down'), self.peer)
            raise
        finally:
            transport.close()
            self.path.unlink(missing_ok=True)

    async def _transfer(self, transport: asyncio.DatagramTransport, packets: asyncio.Queue) -> None:
        reply = oack(self.options) if self.options else ack(0)
        with open(self.path, 'wb') as handle:
            last_block = await self._receive(transport, packets, handle, reply)
        try:
            await self.receiver.ingest(
                device=self.device,
                source_ip=self.source_ip,
                protocol=PUSH_TFTP,
                filename=self.filename,
                path=self.path,
            )
        except Exception as exc:
            logger.exception('tftp_ingest_failed', extra={'file': self.filename})
            transport.sendto(error(ERR_UNDEFINED, 'the backup could not be stored, try again later'), self.peer)
            self._rejected(REASON_ERROR, f'could not stage the backup: {exc}')
            raise TransferFailed('staging failed') from exc
        final = ack(last_block)
        transport.sendto(final, self.peer)
        await self._dally(transport, packets, final, last_block)

    async def _receive(
        self, transport: asyncio.DatagramTransport, packets: asyncio.Queue, handle: BinaryIO, reply: bytes
    ) -> int:
        """Receive every block; return the last block number (not yet acknowledged)."""
        limit = self.receiver.config.max_file_size
        decoder = NetasciiDecoder() if self.netascii else None
        expected, size, retries = 1, 0, 0
        transport.sendto(reply, self.peer)
        while True:
            try:
                packet, addr = await asyncio.wait_for(packets.get(), self.timeout)
            except TimeoutError:
                retries += 1
                if retries > MAX_RETRIES:
                    raise TransferFailed('timed out') from None
                transport.sendto(reply, self.peer)
                continue
            if addr[:2] != self.peer[:2]:
                transport.sendto(error(ERR_UNKNOWN_TID, 'unknown transfer id'), addr)
                continue
            opcode = struct.unpack('!H', packet[:2])[0] if len(packet) >= 2 else 0
            if opcode == ERROR:
                raise TransferFailed('the client gave up')
            if opcode != DATA or len(packet) < 4:
                transport.sendto(error(ERR_ILLEGAL_OPERATION, 'expected data'), self.peer)
                raise TransferFailed('unexpected packet')
            block = struct.unpack('!H', packet[2:4])[0]
            if block != expected:
                if block == (expected - 1) & 0xFFFF:
                    transport.sendto(reply, self.peer)  # our acknowledgement was lost
                continue
            payload = packet[4:]
            size += len(payload)
            if size > limit:
                transport.sendto(error(ERR_DISK_FULL, f'files may be at most {limit} bytes'), self.peer)
                self._rejected(REASON_TOO_LARGE, f'larger than {limit} bytes')
                raise TransferFailed('too large')
            last = len(payload) < self.blksize
            handle.write(decoder.decode(payload, final=last) if decoder else payload)
            retries = 0
            if last:
                return block
            reply = ack(block)
            transport.sendto(reply, self.peer)
            expected = (expected + 1) & 0xFFFF

    async def _dally(
        self, transport: asyncio.DatagramTransport, packets: asyncio.Queue, final: bytes, block: int
    ) -> None:
        """Acknowledge repeats of the last block for a while, in case the final acknowledgement was lost."""
        loop = asyncio.get_running_loop()
        until = loop.time() + 2 * self.timeout
        while (remaining := until - loop.time()) > 0:
            try:
                packet, addr = await asyncio.wait_for(packets.get(), remaining)
            except TimeoutError:
                return
            if addr[:2] == self.peer[:2] and packet[:4] == data(block, b''):
                transport.sendto(final, self.peer)
