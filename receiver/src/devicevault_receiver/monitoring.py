"""The monitoring relay: an HTTPS listener answering Zabbix proxies from the published device snapshots.

``GET /device/?ip=<address>&id=<id>`` (also ``/api/monitoring/device/``, so a
URL copied from the orchestrator works) answers exactly as the orchestrator's
own ``device/`` endpoint does (``devicevault_protocol.monitoring.device_response``),
from the snapshot of the token owner. Like the rest of the receiver it never
touches the database:

- **Tokens** come from the assignment as digests (``receiver.monitoring.tokens``).
  A request is refused with the same 401 whatever the cause (malformed, unknown,
  expired, or a source address outside the token's networks); the cause goes to
  the orchestrator as a ``monitoring.refused`` event, at most once a minute per
  address. Each token is rate-limited here (429), at the assignment's ``rate``.
- **Snapshots** are watched every ``SNAPSHOT_POLL_SECONDS``: each owner's pointer
  is read, and only a new generation's blob fetched. A snapshot is used only once
  its pointer's signature (the pinned orchestrator key) and its blob's hash check
  out; one that fails is ignored, the previous kept, and a
  ``monitoring.snapshot_rejected`` event sent. With no current snapshot the relay
  answers 503 ``{"error": "stale"}``.
- **Use** is reported every ``USAGE_REPORT_SECONDS`` as ``monitoring.used``: per
  token, the request count and the source addresses seen.
"""

import asyncio
import hmac
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from aiohttp import web
from redis.exceptions import RedisError

from devicevault_protocol import monitoring as protocol
from devicevault_protocol import signing
from devicevault_protocol.logs import get_logger
from devicevault_protocol.push import normalise_address

from .config import RelayToken

if TYPE_CHECKING:
    from .receiver import Receiver

logger = get_logger('devicevault.receiver.monitoring')

PATHS = ('/device/', '/device', '/api/monitoring/device/', '/api/monitoring/device')
INVALID_TOKEN = {'detail': 'Invalid or expired token.'}
THROTTLED = {'detail': 'Request was throttled.'}
STALE = {'error': 'stale'}


@dataclass
class Usage:
    requests: int = 0
    addresses: set[str] = field(default_factory=set)
    last_used_at: datetime | None = None


class RelayListener:
    """Starts, stops and restarts the relay as the assignment changes, and keeps its snapshots current."""

    def __init__(self, receiver: Receiver, *, now: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self.receiver = receiver
        self._now = now
        self._runner: web.AppRunner | None = None
        self._tasks: list[asyncio.Task] = []
        self._wake = asyncio.Event()
        self.bound: tuple[str, int] | None = None
        self.error = ''
        self.snapshots: dict[int, protocol.Snapshot] = {}
        self.snapshot_error = ''
        self._rejected: dict[int, str] = {}  # owner -> the last bad generation reported
        self._windows: dict[str, tuple[int, int]] = {}  # prefix -> (window, requests in it)
        self._usage: dict[str, Usage] = {}
        self.requests = 0
        self.refused = 0
        self.throttled = 0

    @property
    def config(self):
        return self.receiver.config.monitoring

    # --- lifecycle ------------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """The ``monitoring`` part of the receiver's heartbeat."""
        now = self._now()
        certificate = self.receiver.certificate
        return {
            'enabled': self.config.enabled,
            'port': self.config.port,
            'listening': self.bound is not None,
            'error': self.error or self.snapshot_error,
            'certificate_fingerprint': certificate.fingerprint if certificate else '',
            'tokens': len(self.config.tokens),
            'snapshots': {
                str(owner): {
                    'generation': snapshot.generation,
                    'published_at': snapshot.published_at.isoformat(),
                    'devices': len(snapshot.devices),
                    'stale': snapshot.stale(now),
                }
                for owner, snapshot in sorted(self.snapshots.items())
            },
            'requests': self.requests,
            'refused': self.refused,
            'throttled': self.throttled,
        }

    async def configure(self) -> None:
        config = self.receiver.config
        owners = self.config.owners
        self.snapshots = {o: s for o, s in self.snapshots.items() if o in owners}
        self._windows = {p: w for p, w in self._windows.items() if self.config.token(p)}
        wanted = (config.bind_address, self.config.port) if self.config.enabled else None
        if wanted != self.bound or (wanted is not None and self._runner is None):
            await self.stop()
            if wanted is None:
                return
            await self._listen(*wanted)
        if self.config.enabled:
            if not self._tasks:
                self._tasks = [asyncio.create_task(self._watch()), asyncio.create_task(self._report())]
            self._wake.set()  # load new owners' snapshots now

    async def _listen(self, address: str, port: int) -> None:
        try:
            context = self.receiver.load_certificate().ssl_context()
            app = web.Application()
            for path in PATHS:
                app.router.add_get(path, self.handle)
            runner = web.AppRunner(app, access_log=None, handle_signals=False)
            await runner.setup()
            try:
                await web.TCPSite(runner, host=address or None, port=port, ssl_context=context).start()
            except BaseException:
                await runner.cleanup()
                raise
        except (OSError, ValueError) as exc:
            self.error = f'cannot listen on {address or "*"}:{port}: {getattr(exc, "strerror", None) or exc}'
            logger.error('monitoring_listen_failed', extra={'port': port, 'error': self.error})
            return
        self._runner = runner
        self.bound = (address, port)
        self.error = ''
        logger.info('monitoring_listening', extra={'address': address or '*', 'port': port})

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks = []
        await self.flush()
        if self._runner is not None:
            await self._runner.cleanup()
            logger.info('monitoring_stopped', extra={'port': self.bound[1] if self.bound else None})
        self._runner = None
        self.bound = None
        if not self.config.enabled:
            self.snapshots = {}

    # --- requests -------------------------------------------------------------------------

    def check(self, authorization: str, address: str, now: datetime) -> tuple[RelayToken | None, str, str]:
        """The assigned token ``authorization`` names, usable from ``address``: (token, prefix, cause)."""
        scheme, _, raw = authorization.strip().partition(' ')
        parsed = protocol.parse_token(raw.strip()) if scheme.lower() == 'bearer' else None
        if parsed is None:
            return None, '', protocol.CAUSE_MALFORMED
        prefix, secret = parsed
        token = self.config.token(prefix)
        digest = protocol.token_digest(secret)
        if token is None or not hmac.compare_digest(token.digest.encode(), digest.encode()):
            return None, prefix, protocol.CAUSE_UNKNOWN
        if token.expires_at <= now:
            return None, prefix, protocol.CAUSE_EXPIRED
        if not token.allows(address):
            return None, prefix, protocol.CAUSE_NETWORK
        return token, prefix, ''

    def over_rate(self, prefix: str, at: float | None = None) -> bool:
        """Count a request against the token's limit; True once it is over (a fixed window, as the API's)."""
        limit, period = self.config.limit
        window = int((time.time() if at is None else at) // period)
        current, count = self._windows.get(prefix, (window, 0))
        count = count + 1 if current == window else 1
        self._windows[prefix] = (window, count)
        return count > limit

    def answer(self, token: RelayToken, *, ip: str, device_id: str, now: datetime) -> tuple[int, dict]:
        snapshot = self.snapshots.get(token.owner)
        if snapshot is None or snapshot.stale(now):
            return 503, STALE
        return 200, protocol.device_response(snapshot, ip=ip, device_id=device_id, now=now)

    async def handle(self, request: web.Request) -> web.Response:
        now = self._now()
        address = _source(request)
        token, prefix, cause = self.check(request.headers.get('Authorization', ''), address, now)
        if token is None:
            self.refused += 1
            loop = asyncio.get_running_loop()
            loop.run_in_executor(
                None,
                lambda: self.receiver.events.monitoring_refused(source_ip=address, prefix=prefix, cause=cause),
            )
            return web.json_response(INVALID_TOKEN, status=401, headers={'WWW-Authenticate': 'Bearer'})
        if self.over_rate(token.prefix):
            self.throttled += 1
            return web.json_response(THROTTLED, status=429)
        self.requests += 1
        self._note_use(token.prefix, address, now)
        status, body = self.answer(
            token, ip=request.query.get('ip', ''), device_id=request.query.get('id', ''), now=now
        )
        return web.json_response(body, status=status)

    def _note_use(self, prefix: str, address: str, now: datetime) -> None:
        usage = self._usage.setdefault(prefix, Usage())
        usage.requests += 1
        usage.last_used_at = now
        if len(usage.addresses) < protocol.MAX_REPORTED_ADDRESSES:
            usage.addresses.add(address)

    # --- reporting ------------------------------------------------------------------------

    def take_usage(self) -> list[dict[str, Any]]:
        """The use since the last report, as ``monitoring.used`` entries (call it on the event loop)."""
        usage, self._usage = self._usage, {}
        return [
            {
                'prefix': prefix,
                'requests': use.requests,
                'addresses': sorted(use.addresses),
                'last_used_at': use.last_used_at.isoformat() if use.last_used_at else None,
            }
            for prefix, use in sorted(usage.items())[: protocol.MAX_REPORTED_TOKENS]
        ]

    def send_usage(self, entries: list[dict[str, Any]]) -> None:
        if not entries:
            return
        try:
            self.receiver.events.send_monitoring(protocol.EVENT_USED, tokens=entries)
        except Exception:  # the broker being down must not break the listener
            logger.exception('monitoring_use_not_sent')

    async def flush(self) -> None:
        """Report the use since the last report (the send runs off the event loop)."""
        entries = self.take_usage()
        if entries:
            await asyncio.to_thread(self.send_usage, entries)

    async def _report(self) -> None:
        while True:
            await asyncio.sleep(protocol.USAGE_REPORT_SECONDS)
            await self.flush()

    # --- snapshots ------------------------------------------------------------------------

    async def _watch(self) -> None:
        while True:
            self._wake.clear()
            await self.refresh()
            try:
                await asyncio.wait_for(self._wake.wait(), protocol.SNAPSHOT_POLL_SECONDS)
            except TimeoutError:
                pass

    async def refresh(self) -> None:
        """Load every owner's snapshot that has a new generation (the Redis reads run off the event loop)."""
        pinned = self.receiver.events.identity.orchestrator_key
        if not pinned:
            return
        key = signing.public_key_from_b64(pinned)
        current = {owner: snapshot.generation for owner, snapshot in self.snapshots.items()}
        owners = sorted(self.config.owners)
        try:
            results = await asyncio.to_thread(self._fetch_all, owners, current, key)
        except RedisError as exc:
            self.snapshot_error = f'cannot read snapshots: {exc}'
            logger.warning('monitoring_snapshots_unavailable', extra={'error': str(exc)})
            return
        self.snapshot_error = ''
        for owner, (snapshot, problem) in results.items():
            if snapshot is not None and owner in self.config.owners:
                self.snapshots[owner] = snapshot
                self._rejected.pop(owner, None)
                logger.info(
                    'monitoring_snapshot_loaded',
                    extra={'owner': owner, 'generation': snapshot.generation, 'devices': len(snapshot.devices)},
                )
            elif problem is not None:
                await self._reject(owner, *problem)

    def _fetch_all(self, owners: list[int], current: dict[int, str], key) -> dict[int, tuple]:
        return {owner: self._fetch(owner, current.get(owner), key) for owner in owners}

    def _fetch(self, owner: int, generation: str | None, key) -> tuple[protocol.Snapshot | None, tuple | None]:
        """(new snapshot, None), (None, (generation, reason)) when one failed its checks, or (None, None)."""
        redis = self.receiver.ingestor.redis
        try:
            pointer = protocol.read_pointer(redis, owner, key)
        except protocol.SnapshotError as exc:
            return None, ('', str(exc))
        if pointer is None or pointer.get('generation') == generation:
            return None, None
        try:
            return protocol.load(redis, owner, key, pointer=pointer), None
        except protocol.SnapshotError as exc:
            return None, (str(pointer.get('generation') or ''), str(exc))

    async def _reject(self, owner: int, generation: str, reason: str) -> None:
        seen = f'{generation}:{reason}'
        if self._rejected.get(owner) == seen:
            return  # reported already
        self._rejected[owner] = seen
        logger.error('monitoring_snapshot_rejected', extra={'owner': owner, 'generation': generation, 'reason': reason})
        try:
            await asyncio.to_thread(
                self.receiver.events.send_monitoring,
                protocol.EVENT_SNAPSHOT_REJECTED,
                owner=owner,
                generation=generation,
                reason=reason[:255],
            )
        except Exception:
            logger.exception('monitoring_rejection_not_sent')


def _source(request: web.Request) -> str:
    """The peer's address from the socket (receivers use host networking, so it is the proxy's own)."""
    peer = request.transport.get_extra_info('peername') if request.transport else None
    try:
        return normalise_address(str(peer[0]))
    except TypeError, IndexError, ValueError:
        return ''
