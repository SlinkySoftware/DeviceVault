"""The SCP/SFTP listener, driven by a real asyncssh client over localhost."""

import asyncio
import socket

import asyncssh
import pytest

from devicevault_protocol import blobs
from devicevault_protocol.jobs import blob_key
from devicevault_receiver.config import ReceiverConfig
from devicevault_receiver.ingest import Ingestor
from devicevault_receiver.receiver import Receiver

CONTENT = b'hostname edge-01\n'


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def config(port, **overrides):
    device = {'id': 7, 'ip': '127.0.0.1', 'push_mode': 'ssh', 'filename_pattern': ''}
    device.update(overrides.pop('device', {}))
    ssh = {'enabled': True, 'port': port, 'username': 'dv', 'password': 'pw', **overrides.pop('ssh', {})}
    return ReceiverConfig.model_validate({'bind_address': '127.0.0.1', 'ssh': ssh, 'devices': [device], **overrides})


@pytest.fixture
def run(redis, events, spool, tmp_path):
    """Run ``scenario(receiver, port, upload_path)`` against a listening receiver."""

    def runner(scenario, **overrides):
        upload = tmp_path / 'local-confg'
        upload.write_bytes(CONTENT)
        port = free_port()

        async def main():
            receiver = Receiver(
                ingestor=Ingestor(redis=redis, events=events, spool_dir=spool),
                events=events,
                host_key=asyncssh.generate_private_key('ssh-ed25519'),
                spool_dir=spool,
            )
            await receiver.apply(config(port, **overrides))
            try:
                return await scenario(receiver, port, upload)
            finally:
                await receiver.close()

        return asyncio.run(main())

    return runner


def connect(port, username='dv', password='pw', **kwargs):
    return asyncssh.connect(
        '127.0.0.1', port, username=username, password=password, known_hosts=None, client_keys=None, **kwargs
    )


def staged(redis, sent):
    received = [e for e in sent.events() if e['event'] == 'received']
    return [blobs.get(redis, blob_key(e['job_id'])) for e in received], received


def rejections(sent):
    return [(e['reason'], e.get('filename', '')) for e in sent.events() if e['event'] == 'rejected']


def test_sftp_uploads_are_staged(run, redis, sent, spool):
    async def scenario(receiver, port, upload):
        async with connect(port) as conn, conn.start_sftp_client() as sftp:
            await sftp.put(str(upload), 'edge-confg')

    run(scenario)

    contents, [event] = staged(redis, sent)
    assert contents == [CONTENT]
    assert (event['device_id'], event['source_ip'], event['filename']) == (7, '127.0.0.1', 'edge-confg')
    assert list(spool.iterdir()) == []  # the connection's spool directory is gone


def test_scp_uploads_are_staged_under_their_base_name(run, redis, sent):
    async def scenario(receiver, port, upload):
        async with connect(port) as conn:
            await asyncssh.scp(str(upload), (conn, '/flash/edge-confg'))
            await asyncssh.scp(str(upload), (conn, '.'))

    run(scenario)

    contents, events = staged(redis, sent)
    assert contents == [CONTENT, CONTENT]
    assert [e['filename'] for e in events] == ['edge-confg', 'local-confg']


def test_authorised_keys_log_in_without_a_password(run, redis, sent):
    key = asyncssh.generate_private_key('ssh-ed25519')

    async def scenario(receiver, port, upload):
        async with asyncssh.connect(
            '127.0.0.1', port, username='dv', client_keys=[key], known_hosts=None, password=None
        ) as conn:
            await asyncssh.scp(str(upload), (conn, 'edge-confg'))

    run(scenario, ssh={'password': '', 'authorized_keys': key.export_public_key().decode()})

    assert staged(redis, sent)[0] == [CONTENT]


@pytest.mark.parametrize(
    ('overrides', 'login', 'reason'),
    [
        ({}, {'password': 'wrong'}, 'auth_failed'),
        ({}, {'username': 'root'}, 'auth_failed'),
        ({'device': {'ip': '192.0.2.10'}}, {}, 'unknown_source'),
        ({'device': {'push_mode': 'tftp'}}, {}, 'wrong_protocol'),
    ],
)
def test_logins_are_refused_and_reported(run, sent, overrides, login, reason):
    async def scenario(receiver, port, upload):
        with pytest.raises(asyncssh.PermissionDenied):
            async with connect(port, **login):
                pass

    run(scenario, **overrides)

    assert reason in [r for r, _ in rejections(sent)]
    assert staged(None, sent)[1] == []


def test_filenames_must_match_the_device_pattern(run, redis, sent):
    async def scenario(receiver, port, upload):
        async with connect(port) as conn, conn.start_sftp_client() as sftp:
            with pytest.raises(asyncssh.SFTPPermissionDenied):
                await sftp.put(str(upload), 'notes.txt')
            await sftp.put(str(upload), 'edge-confg')

    run(scenario, device={'filename_pattern': '*-confg'})

    assert rejections(sent) == [('filename', 'notes.txt')]
    assert [e['filename'] for e in staged(redis, sent)[1]] == ['edge-confg']


def test_files_over_the_size_limit_are_refused(run, redis, sent, tmp_path):
    big = tmp_path / 'big-confg'
    big.write_bytes(b'x' * 5000)

    async def scenario(receiver, port, upload):
        async with connect(port) as conn, conn.start_sftp_client() as sftp:
            with pytest.raises(asyncssh.SFTPFailure):
                await sftp.put(str(big), 'big-confg')
        async with connect(port) as conn:
            with pytest.raises(asyncssh.SFTPError):
                await asyncssh.scp(str(big), (conn, 'big-confg'))

    run(scenario, max_file_size=4096)

    assert ('too_large', 'big-confg') in rejections(sent)
    assert staged(redis, sent)[1] == []


def test_nothing_can_be_read_listed_or_run(run, sent):
    async def scenario(receiver, port, upload):
        async with connect(port) as conn:
            async with conn.start_sftp_client() as sftp:
                await sftp.put(str(upload), 'edge-confg')
                with pytest.raises(asyncssh.SFTPPermissionDenied):
                    await sftp.open('edge-confg', 'rb')
                with pytest.raises(asyncssh.SFTPPermissionDenied):
                    await sftp.listdir('.')
                with pytest.raises(asyncssh.SFTPPermissionDenied):
                    await sftp.remove('edge-confg')
            with pytest.raises((asyncssh.ChannelOpenError, asyncssh.ProcessError)):
                await conn.run('id', check=True)
            with pytest.raises(asyncssh.ChannelOpenError):
                await conn.create_connection(asyncssh.SSHTCPSession, '127.0.0.1', port)

    run(scenario)


def test_listeners_follow_the_configuration(run):
    async def scenario(receiver, port, upload):
        assert receiver.status()['listeners']['ssh'] == {'enabled': True, 'port': port, 'listening': True, 'error': ''}

        await receiver.apply(ReceiverConfig())
        assert receiver.status()['listeners']['ssh']['listening'] is False
        with pytest.raises(OSError):
            await connect(port)

        # A port that is taken is reported, not fatal.
        with socket.socket() as taken:
            taken.bind(('127.0.0.1', 0))
            taken.listen()
            await receiver.apply(config(taken.getsockname()[1]))
            status = receiver.status()['listeners']['ssh']
            assert status['listening'] is False and 'cannot listen' in status['error']

        await receiver.apply(config(port))
        async with connect(port):
            pass

    run(scenario)


def test_staging_failures_fail_the_upload(run, sent, monkeypatch):
    def broken(**kwargs):
        raise ConnectionError('redis is down')

    async def scenario(receiver, port, upload):
        monkeypatch.setattr(receiver.ingestor, 'ingest', broken)
        async with connect(port) as conn, conn.start_sftp_client() as sftp:
            with pytest.raises(asyncssh.SFTPFailure):
                await sftp.put(str(upload), 'edge-confg')

    run(scenario)

    assert rejections(sent) == [('error', 'edge-confg')]


def test_sftp_sessions_report_success_like_openssh(spool):
    # OpenSSH's scp (SFTP mode) treats a session without an exit status as a failure.
    from devicevault_receiver.ssh import UploadServer

    class Channel:
        status = None

        def get_connection(self):
            return self

        def get_owner(self):
            return None

        def exit(self, status):
            self.status = status

    class Receiver:
        spool_dir = spool

    channel = Channel()
    server = UploadServer(channel, Receiver())
    server.exit()

    assert channel.status == 0 and not server.root.exists()
