"""Monitoring: API token strings, and the signed device snapshots the orchestrator publishes for relays.

The orchestrator's scheduler leader publishes one snapshot per **relay owner**
(a service account holding a live ``monitoring`` token), every publish
interval. A snapshot is a JSON blob (``blobs``) with a signed pointer::

    dv:monitoring:relay:<owner>               -> envelope signed by the orchestrator, payload
        {"owner": 7, "generation": "<hex>", "published_at": "<iso>", "interval": 900,
         "blob": {"key": "dv:monitoring:relay:7:<generation>", "sha256", "size"}}
    dv:monitoring:relay:<owner>:<generation>  -> {"owner": 7, "published_at", "interval",
                                                  "devices": {"<id>": {...}}, "by_ip": {"<ip>": <id>}}

Both expire after ``STALE_INTERVALS`` intervals, so a stopped publisher shows as
stale rather than as old data that looks fresh. Readers (the orchestrator's own
``device/`` endpoint and receiver relays) verify the pointer against the pinned
orchestrator key and the blob against its hash, then answer with
``device_response``, so both paths give the same answer.

Receiver relays learn which tokens to accept from their assignment (``receiver.monitoring``;
the relay listens on the receiver's ``bind_address``, like SSH and TFTP)::

    "monitoring": {"enabled": true, "port": 8443, "rate": "600/min",
                   "tokens": [{"prefix": "ab12cd34", "digest": "<sha256 hex of the secret>", "owner": 7,
                               "expires_at": "<iso>", "allowed_networks": ["192.0.2.0/24"]}]}

``tokens`` lists every live ``monitoring`` token of every relay owner (never a
secret), and is empty while the relay is disabled. ``rate`` is
``DV_API_TOKEN_RATE``, enforced per token by each relay on its own.

Receiver -> orchestrator: Celery task ``MONITORING_EVENT_TASK`` on the
orchestrator queue, argument an envelope signed with the receiver's key, payload::

    {"event": "monitoring.used", "worker_id", "at",
     "tokens": [{"prefix", "requests": 12, "addresses": ["192.0.2.5"], "last_used_at": "<iso>"}]}
    {"event": "monitoring.refused", "worker_id", "at", "source_ip", "prefix": "" | "ab12cd34",
     "cause": one of REFUSAL_CAUSES}
    {"event": "monitoring.snapshot_rejected", "worker_id", "at", "owner": 7, "generation", "reason"}

``used`` is sent every ``USAGE_REPORT_SECONDS`` when there was any use,
``refused`` at most once a ``REFUSAL_WINDOW_SECONDS`` per source address, and
``snapshot_rejected`` once per bad generation. Heartbeats from a receiver add,
under ``receiver``::

    "monitoring": {"enabled", "port", "listening", "error", "certificate_fingerprint", "tokens": 2,
                   "snapshots": {"<owner>": {"generation", "published_at", "devices", "stale"}},
                   "requests", "refused", "throttled"}

(counts since the receiver started).
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from redis import Redis

from devicevault_protocol import blobs, signing
from devicevault_protocol.push import normalise_address

MONITORING_EVENT_TASK = 'orchestrator.monitoring_event'

EVENT_USED = 'monitoring.used'
EVENT_REFUSED = 'monitoring.refused'
EVENT_SNAPSHOT_REJECTED = 'monitoring.snapshot_rejected'
EVENTS = (EVENT_USED, EVENT_REFUSED, EVENT_SNAPSHOT_REJECTED)

# Why a token was refused (the orchestrator adds revoked and inactive_user; to a relay those are unknown).
CAUSE_MALFORMED = 'malformed'
CAUSE_UNKNOWN = 'unknown'
CAUSE_EXPIRED = 'expired'
CAUSE_NETWORK = 'network'
REFUSAL_CAUSES = (CAUSE_MALFORMED, CAUSE_UNKNOWN, CAUSE_EXPIRED, CAUSE_NETWORK)

SNAPSHOT_POLL_SECONDS = 30
USAGE_REPORT_SECONDS = 60
REFUSAL_WINDOW_SECONDS = 60
# Bounds on one usage report, so a busy relay's event stays small.
MAX_REPORTED_TOKENS = 200
MAX_REPORTED_ADDRESSES = 20

_RATE_PERIODS = {'sec': 1, 'min': 60, 'hour': 3600}


def parse_rate(value: str) -> tuple[int, int]:
    """``DV_API_TOKEN_RATE`` (``600/min``) as (requests, seconds). Raises ValueError when malformed."""
    try:
        count, period = str(value).split('/')
        requests, seconds = int(count), _RATE_PERIODS[period]
    except ValueError, KeyError:
        raise ValueError(f'a rate looks like 600/min, not {value!r}') from None
    if requests < 1:
        raise ValueError(f'a rate allows at least one request, not {value!r}')
    return requests, seconds


# --- token strings ------------------------------------------------------------------------

TOKEN_PREFIX = 'dvt'
TOKEN_PREFIX_LENGTH = 8


def parse_token(raw: str) -> tuple[str, str] | None:
    """(prefix, secret) of a well-formed ``dvt_<prefix>_<secret>`` string, else None."""
    parts = raw.split('_', 2)
    if len(parts) != 3 or parts[0] != TOKEN_PREFIX or len(parts[1]) != TOKEN_PREFIX_LENGTH or not parts[2]:
        return None
    return parts[1], parts[2]


def token_digest(secret: str) -> str:
    """What is stored and compared for a token's secret: its SHA-256, in hex."""
    return hashlib.sha256(secret.encode()).hexdigest()


# --- relay snapshots ----------------------------------------------------------------------

STALE_INTERVALS = 3
DEFAULT_RELAY_PORT = 8443


def pointer_key(owner: int) -> str:
    return f'dv:monitoring:relay:{owner}'


def blob_key(owner: int, generation: str) -> str:
    return f'dv:monitoring:relay:{owner}:{generation}'


@dataclass(frozen=True)
class Snapshot:
    owner: int
    generation: str
    published_at: datetime
    interval: int
    devices: dict[str, dict[str, Any]]
    by_ip: dict[str, int]

    def stale(self, now: datetime | None = None) -> bool:
        age = ((now or datetime.now(UTC)) - self.published_at).total_seconds()
        return age > STALE_INTERVALS * self.interval


class SnapshotError(ValueError):
    """A snapshot that is present but fails verification."""


def publish(
    redis: Redis, key, owner: int, devices: dict[int, dict], by_ip: dict[str, int], *, interval: int, now=None
) -> dict:
    """Stage a snapshot and swap its pointer to it. ``key`` is the orchestrator's signing key."""
    now = now or datetime.now(UTC)
    generation = hashlib.sha256(f'{owner}:{now.isoformat()}'.encode()).hexdigest()[:16]
    ttl = STALE_INTERVALS * interval
    document = {
        'owner': owner,
        'published_at': now.isoformat(),
        'interval': interval,
        'devices': {str(pk): row for pk, row in devices.items()},
        'by_ip': by_ip,
    }
    staged = blobs.put(redis, blob_key(owner, generation), json.dumps(document, separators=(',', ':')).encode(), ttl)
    pointer = {
        'owner': owner,
        'generation': generation,
        'published_at': now.isoformat(),
        'interval': interval,
        'blob': staged,
    }
    redis.set(pointer_key(owner), json.dumps(signing.sign(pointer, key, 'orchestrator', now=now)), ex=ttl)
    return pointer


def read_pointer(redis: Redis, owner: int, public_key) -> dict | None:
    """The verified pointer for ``owner``, None when there is none. Raises SnapshotError when forged."""
    raw = redis.get(pointer_key(owner))
    if raw is None:
        return None
    try:
        pointer = signing.verify(json.loads(raw), public_key)
    except (ValueError, signing.SignatureError) as exc:
        raise SnapshotError(f'pointer: {exc}') from exc
    if pointer.get('owner') != owner or not isinstance(pointer.get('blob'), dict):
        raise SnapshotError('pointer for another owner')
    return pointer


def load(redis: Redis, owner: int, public_key, *, pointer: dict | None = None) -> Snapshot | None:
    """The verified snapshot for ``owner``; None when there is none (or it expired). Raises SnapshotError."""
    pointer = pointer or read_pointer(redis, owner, public_key)
    if pointer is None:
        return None
    raw = blobs.get(redis, pointer['blob']['key'])
    if raw is None:
        return None
    if blobs.sha256(raw) != pointer['blob'].get('sha256'):
        raise SnapshotError('blob does not match its pointer')
    try:
        document = json.loads(raw)
        return Snapshot(
            owner=owner,
            generation=pointer['generation'],
            published_at=datetime.fromisoformat(pointer['published_at']),
            interval=int(pointer['interval']),
            devices=document['devices'],
            by_ip={str(ip): int(pk) for ip, pk in document['by_ip'].items()},
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise SnapshotError(f'blob: {exc}') from exc


def device_response(snapshot: Snapshot, *, ip: str = '', device_id: str = '', now: datetime | None = None) -> dict:
    """The ``device/`` answer: ``id`` wins when given, else the active device with that address.

    Ages are worked out at answer time, so they keep growing between publishes.
    """
    now = now or datetime.now(UTC)
    key = str(device_id).strip()
    if not key and ip:
        found = snapshot.by_ip.get(_address(ip.strip()))
        key = str(found) if found is not None else ''
    row = snapshot.devices.get(key) if key else None
    published = snapshot.published_at.isoformat()
    if row is None:
        return {'found': 0, 'published_at': published, 'published_age': _age(snapshot.published_at, now)}
    answer = dict(row)
    last = answer.get('last_success_at') or 0
    answer['last_success_age'] = int(now.timestamp() - last) if last else 0
    answer.update(found=1, published_at=published, published_age=_age(snapshot.published_at, now))
    return answer


def _address(ip: str) -> str:
    """Any spelling of an address (IPv4-mapped IPv6, upper-case hex) as devices are indexed; else as given."""
    try:
        return normalise_address(ip)
    except ValueError:
        return ip


def _age(moment: datetime, now: datetime) -> int:
    return max(0, int((now - moment).total_seconds()))
