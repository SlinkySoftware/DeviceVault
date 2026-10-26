"""Entry point: ``python -m devicevault_receiver`` (the image's ``dv-receiver``).

Needs only DV_BROKER_URL and DV_REDIS_URL (plus DV_WORKER_NAME for display).
The receiver registers, waits for an administrator to approve it as a
receiver, and listens on whatever its assignment enables.
"""

import asyncio
import shutil
import signal

from devicevault_protocol.env import env_str
from devicevault_protocol.identity import state_dir
from devicevault_protocol.logs import get_logger

from . import certificate as tls
from . import hostkey
from .agent import ReceiverAgent
from .app import app, bus, identity, redis_client
from .events import Events
from .ingest import Ingestor
from .receiver import Receiver

logger = get_logger('devicevault.receiver')


def main() -> None:
    spool_dir = state_dir() / 'spool'
    shutil.rmtree(spool_dir, ignore_errors=True)  # uploads cut short by a restart
    spool_dir.mkdir(parents=True, mode=0o700)

    events = Events(identity, app.send_task)
    receiver = Receiver(
        ingestor=Ingestor(redis=redis_client, events=events, spool_dir=spool_dir),
        events=events,
        host_key=hostkey.load_or_create(),
        spool_dir=spool_dir,
        certificate=tls.load_or_create(),
    )
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    name = env_str('DV_WORKER_NAME', 'receiver')
    agent = ReceiverAgent(
        receiver=receiver,
        loop=loop,
        identity=identity,
        name=name,
        broker_url=bus.broker_url,
        send_task=app.send_task,
    )
    agent.log_identity()
    logger.warning('receiver_host_key', extra={'fingerprint': hostkey.fingerprint(receiver.host_key)})
    logger.warning('receiver_relay_certificate', extra={'fingerprint': receiver.load_certificate().fingerprint})

    stopping = asyncio.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stopping.set)
    agent.start()
    try:
        loop.run_until_complete(stopping.wait())
    finally:
        agent.stop()
        loop.run_until_complete(receiver.close())
        loop.close()
