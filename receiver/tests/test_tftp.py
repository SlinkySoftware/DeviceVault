"""The TFTP listener, driven by a small blocking TFTP client over localhost."""

import asyncio
import socket
import struct

import asyncssh
import pytest

from devicevault_protocol import blobs
from devicevault_protocol.jobs import blob_key
from devicevault_receiver import tftp
from devicevault_receiver.config import ReceiverConfig
from devicevault_receiver.ingest import Ingestor
from devicevault_receiver.receiver import Receiver


def free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def config(port, **overrides):
    device = {'id': 9, 'ip': '127.0.0.1', 'push_mode': 'tftp', 'filename_pattern': ''}
    device.update(overrides.pop('device', {}))
    return ReceiverConfig.model_validate(
        {'bind_address': '127.0.0.1', 'tftp': {'enabled': True, 'port': port}, 'devices': [device], **overrides}
    )


class Client:
    """Just enough TFTP to upload, with hooks to misbehave."""

    def __init__(self, port, timeout=3.0):
        self.server = ('127.0.0.1', port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(timeout)

    def close(self):
        self.sock.close()

    def request(self, opcode, filename, mode='octet', **options):
        fields = [filename, mode, *(x for kv in options.items() for x in kv)]
        self.sock.sendto(struct.pack('!H', opcode) + b''.join(f'{f}\0'.encode() for f in fields), self.server)
        packet, self.peer = self.sock.recvfrom(70000)
        return packet

    def recv(self):
        packet, _ = self.sock.recvfrom(70000)
        return packet

    def put(self, filename, content, mode='octet', duplicate_block=None, **options):
        reply = self.request(tftp.WRQ, filename, mode, **{k: str(v) for k, v in options.items()})
        opcode = struct.unpack('!H', reply[:2])[0]
        if opcode == tftp.ERROR:
            return error_of(reply)
        blksize = int(options.get('blksize', 512)) if opcode == tftp.OACK else 512
        chunks = [content[i : i + blksize] for i in range(0, len(content), blksize)]
        if not chunks or len(chunks[-1]) == blksize:
            chunks.append(b'')
        for number, chunk in enumerate(chunks, start=1):
            block = number & 0xFFFF
            self.sock.sendto(tftp.data(block, chunk), self.peer)
            if number == duplicate_block:
                assert self.recv() == tftp.ack(block)
                self.sock.sendto(tftp.data(block, chunk), self.peer)  # as if our ACK was lost
            reply = self.recv()
            if reply[:2] == struct.pack('!H', tftp.ERROR):
                return error_of(reply)
            assert reply == tftp.ack(block), (number, reply)
        return 'ok'


def error_of(packet):
    code = struct.unpack('!H', packet[2:4])[0]
    return code, packet[4:-1].decode()


def make_receiver(redis, events, spool):
    return Receiver(
        ingestor=Ingestor(redis=redis, events=events, spool_dir=spool),
        events=events,
        host_key=asyncssh.generate_private_key('ssh-ed25519'),
        spool_dir=spool,
    )


@pytest.fixture
def run(redis, events, spool):
    """Run ``scenario(receiver, port)`` (blocking client code, in a thread) against a listening receiver."""

    def runner(scenario, **overrides):
        port = free_udp_port()

        async def main():
            receiver = make_receiver(redis, events, spool)
            await receiver.apply(config(port, **overrides))
            try:
                return await asyncio.to_thread(scenario, receiver, port)
            finally:
                await receiver.close()

        return asyncio.run(main())

    return runner


def staged(redis, sent):
    received = [e for e in sent.events() if e['event'] == 'received']
    return [blobs.get(redis, blob_key(e['job_id'])) for e in received], received


def rejections(sent):
    return [(e['reason'], e.get('filename', '')) for e in sent.events() if e['event'] == 'rejected']


@pytest.mark.parametrize('size', [0, 100, 512, 1500])
def test_uploads_are_staged(run, redis, sent, spool, size):
    content = bytes(range(256)) * 8
    content = content[:size]

    def scenario(receiver, port):
        client = Client(port)
        try:
            return client.put('/configs/edge-confg', content)
        finally:
            client.close()

    assert run(scenario) == 'ok'
    contents, [event] = staged(redis, sent)
    assert contents == [content]
    assert (event['device_id'], event['protocol'], event['filename'], event['source_ip']) == (
        9,
        'tftp',
        'edge-confg',
        '127.0.0.1',
    )
    assert list(spool.iterdir()) == []


def test_options_are_negotiated(run, redis, sent):
    content = b'x' * 3000

    def scenario(receiver, port):
        client = Client(port)
        try:
            oack = client.request(tftp.WRQ, 'edge-confg', blksize='1024', tsize=str(len(content)), windowsize='4')
            assert oack == tftp.oack({'blksize': '1024', 'tsize': '3000'})
            for number, start in enumerate(range(0, 3072, 1024), start=1):  # the third block is short: the end
                client.sock.sendto(tftp.data(number, content[start : start + 1024]), client.peer)
                assert client.recv() == tftp.ack(number)
            return 'ok'
        finally:
            client.close()

    assert run(scenario) == 'ok'
    assert staged(redis, sent)[0] == [content]


def test_netascii_is_decoded_across_blocks(run, redis, sent):
    # 511 bytes then CR, so the CR LF pair straddles the first two blocks.
    content = b'a' * 511 + b'\r\nline two\r\0bare cr\r\n'

    def scenario(receiver, port):
        client = Client(port)
        try:
            return client.put('edge-confg', content, mode='netascii')
        finally:
            client.close()

    assert run(scenario) == 'ok'
    assert staged(redis, sent)[0] == [b'a' * 511 + b'\nline two\rbare cr\n']


def test_lost_acknowledgements_and_strangers_do_not_break_a_transfer(run, redis, sent):
    content = b'y' * 2000

    def scenario(receiver, port):
        client = Client(port)
        stranger = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        stranger.settimeout(3)
        try:
            client.request(tftp.WRQ, 'edge-confg')
            stranger.sendto(tftp.data(1, b'evil'), client.peer)
            assert error_of(stranger.recv(100))[0] == tftp.ERR_UNKNOWN_TID
            client.sock.sendto(tftp.data(1, content[:512]), client.peer)
            assert client.recv() == tftp.ack(1)
            client.sock.sendto(tftp.data(1, content[:512]), client.peer)  # a repeat: re-acknowledged, not rewritten
            assert client.recv() == tftp.ack(1)
            for number in (2, 3, 4):
                client.sock.sendto(tftp.data(number, content[(number - 1) * 512 : number * 512]), client.peer)
                assert client.recv() == tftp.ack(number)
            return 'ok'
        finally:
            client.close()
            stranger.close()

    assert run(scenario) == 'ok'
    assert staged(redis, sent)[0] == [content]


def test_block_numbers_wrap(run, redis, sent):
    content = bytes(range(256)) * 2050  # 524,800 bytes in 8-byte blocks: 65,600 blocks, past 65,535

    def scenario(receiver, port):
        client = Client(port)
        try:
            return client.put('edge-confg', content, blksize=8)
        finally:
            client.close()

    assert run(scenario) == 'ok'
    assert staged(redis, sent)[0] == [content]


@pytest.mark.parametrize(
    ('overrides', 'opcode', 'filename', 'options', 'code', 'reason'),
    [
        ({'device': {'ip': '192.0.2.1'}}, tftp.WRQ, 'edge-confg', {}, tftp.ERR_ACCESS_VIOLATION, 'unknown_source'),
        ({'device': {'push_mode': 'ssh'}}, tftp.WRQ, 'edge-confg', {}, tftp.ERR_ACCESS_VIOLATION, 'wrong_protocol'),
        (
            {'device': {'filename_pattern': '*-confg*'}},
            tftp.WRQ,
            'notes.txt',
            {},
            tftp.ERR_ACCESS_VIOLATION,
            'filename',
        ),
        ({'max_file_size': 1024}, tftp.WRQ, 'edge-confg', {'tsize': '5000'}, tftp.ERR_DISK_FULL, 'too_large'),
        ({}, tftp.RRQ, 'edge-confg', {}, tftp.ERR_ACCESS_VIOLATION, None),
    ],
    ids=['unknown-source', 'ssh-device', 'filename', 'tsize', 'read'],
)
def test_requests_are_refused(run, sent, overrides, opcode, filename, options, code, reason):
    def scenario(receiver, port):
        client = Client(port)
        try:
            return error_of(client.request(opcode, filename, **options))
        finally:
            client.close()

    assert run(scenario, **overrides)[0] == code
    assert rejections(sent) == ([(reason, filename)] if reason else [])
    assert staged(None, sent)[1] == []


def test_files_over_the_limit_are_cut_off(run, sent):
    def scenario(receiver, port):
        client = Client(port)
        try:
            return client.put('edge-confg', b'z' * 5000)
        finally:
            client.close()

    assert run(scenario, max_file_size=2048)[0] == tftp.ERR_DISK_FULL
    assert rejections(sent) == [('too_large', 'edge-confg')]
    assert staged(None, sent)[1] == []


def test_staging_failures_fail_the_upload(run, sent, monkeypatch):
    def broken(**kwargs):
        raise ConnectionError('redis is down')

    def scenario(receiver, port):
        monkeypatch.setattr(receiver.ingestor, 'ingest', broken)
        client = Client(port)
        try:
            return client.put('edge-confg', b'hostname edge\n')
        finally:
            client.close()

    assert run(scenario)[0] == tftp.ERR_UNDEFINED
    assert rejections(sent) == [('error', 'edge-confg')]


def test_the_port_follows_the_configuration(redis, events, spool):
    async def main():
        receiver = make_receiver(redis, events, spool)
        port = free_udp_port()
        await receiver.apply(config(port))
        try:
            assert receiver.status()['listeners']['tftp'] == {
                'enabled': True,
                'port': port,
                'listening': True,
                'error': '',
            }
            await receiver.apply(ReceiverConfig())
            assert receiver.status()['listeners']['tftp']['listening'] is False
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as taken:
                taken.bind(('127.0.0.1', 0))
                await receiver.apply(config(taken.getsockname()[1]))
                status = receiver.status()['listeners']['tftp']
                assert status['listening'] is False and 'cannot listen' in status['error']
        finally:
            await receiver.close()

    asyncio.run(main())


@pytest.mark.parametrize(
    ('packet', 'expected'),
    [
        (b'\x00\x02a\x00octet\x00', tftp.Request(2, 'a', 'octet', {})),
        (
            b'\x00\x02a\x00NetASCII\x00blksize\x001024\x00tsize\x00',
            tftp.Request(2, 'a', 'netascii', {'blksize': '1024'}),
        ),
    ],
)
def test_requests_are_parsed(packet, expected):
    assert tftp.parse_request(packet) == expected


@pytest.mark.parametrize('packet', [b'\x00\x02', b'\x00\x02a\x00octet', b'\x00\x02a'])
def test_malformed_requests_are_rejected(packet):
    with pytest.raises(tftp.Malformed):
        tftp.parse_request(packet)


def test_option_negotiation_keeps_sane_values():
    accepted, blksize, timeout = tftp.negotiate({'blksize': '99999', 'timeout': '0', 'tsize': 'x', 'foo': '1'})

    assert (accepted, blksize, timeout) == ({'blksize': str(tftp.MAX_BLKSIZE)}, tftp.MAX_BLKSIZE, tftp.DEFAULT_TIMEOUT)
