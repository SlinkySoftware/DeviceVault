"""Push collection: devices upload their configuration to a receiver.

A receiver is a worker with role ``receiver``. Its assignment (see
``registration``) carries, besides the usual fields::

    "receiver": {
        "bind_address": "" | "<ip>",               # "" listens on every address
        "max_file_size": 536870912,
        "ssh": {"enabled": true, "port": 2222, "username": "devicevault",
                "password": "..." | "password_sealed": {"<worker_id>": "<sealed>"},
                "authorized_keys": "ssh-ed25519 AAAA... comment\\n..."},
        "devices": [{"id": 7, "ip": "192.0.2.1", "push_mode": "ssh", "filename_pattern": "*-confg"}],
        "encryption": {"kid": "...", "public_key": "..."} | null,
    }

Receiver -> orchestrator: Celery task ``PUSH_EVENT_TASK`` on the orchestrator
queue, argument an envelope signed with the receiver's key, payload::

    {"event": "received", "worker_id", "at", "job_id": "<uuid, chosen by the receiver>",
     "device_id": 7, "source_ip": "192.0.2.1", "protocol": "ssh", "filename": "edge-confg",
     "blob": {"key", "sha256", "size"}, "is_binary": false, "encrypted": true,
     "duration_ms": 12, "log": [<log entry>, ...]}

    {"event": "rejected", "worker_id", "at", "source_ip", "protocol",
     "reason": one of REASONS, "filename": "..." | "", "detail": "..."}

The receiver encrypts a backup (when ``encryption`` is set) with the AAD
fields ``job_id`` and ``device_id`` before it stages it, so it picks the job
id; the orchestrator creates the BackupJob with that id.

Heartbeats from a receiver add ``"receiver": {"host_key_fingerprint",
"vault_kid", "devices", "listeners": {"ssh": {"port", "listening", "error"}}}``.
"""

import ipaddress

PUSH_EVENT_TASK = 'orchestrator.push_event'

EVENT_RECEIVED = 'received'
EVENT_REJECTED = 'rejected'

PUSH_OFF = 'off'
PUSH_SSH = 'ssh'  # SCP or SFTP
PROTOCOLS = (PUSH_SSH,)

REASON_UNKNOWN_SOURCE = 'unknown_source'
REASON_AUTH_FAILED = 'auth_failed'
REASON_WRONG_PROTOCOL = 'wrong_protocol'
REASON_FILENAME = 'filename'
REASON_TOO_LARGE = 'too_large'
REASON_DEVICE_CHANGED = 'device_changed'
REASON_ERROR = 'error'
REASONS = (
    REASON_UNKNOWN_SOURCE,
    REASON_AUTH_FAILED,
    REASON_WRONG_PROTOCOL,
    REASON_FILENAME,
    REASON_TOO_LARGE,
    REASON_DEVICE_CHANGED,
    REASON_ERROR,
)

DEFAULT_SSH_PORT = 2222
DEFAULT_MAX_FILE_SIZE = 512 * 1024 * 1024


def normalise_address(address: str) -> str:
    """The canonical text of an IP address: IPv4-mapped IPv6 becomes IPv4, zone ids are dropped."""
    ip = ipaddress.ip_address(address.split('%', 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return str(ip)
