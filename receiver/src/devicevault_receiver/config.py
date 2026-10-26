"""The ``receiver`` section of an assignment (see devicevault_protocol.push), as the receiver uses it."""

import ipaddress
from ipaddress import IPv4Network, IPv6Network
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, PrivateAttr, field_validator

from devicevault_protocol.crypto import unseal
from devicevault_protocol.identity import Identity
from devicevault_protocol.monitoring import DEFAULT_RELAY_PORT, parse_rate
from devicevault_protocol.push import (
    DEFAULT_MAX_FILE_SIZE,
    DEFAULT_SSH_PORT,
    DEFAULT_TFTP_PORT,
    PUSH_OFF,
    normalise_address,
)


class _Model(BaseModel):
    model_config = ConfigDict(extra='ignore', frozen=True)


class SshSettings(_Model):
    enabled: bool = False
    port: int = Field(DEFAULT_SSH_PORT, ge=1, le=65535)
    username: str = ''
    password: str = ''
    authorized_keys: str = ''


class TftpSettings(_Model):
    enabled: bool = False
    port: int = Field(DEFAULT_TFTP_PORT, ge=1, le=65535)


class RelayToken(_Model):
    """A token the monitoring relay accepts: its prefix and secret digest, never the secret."""

    prefix: str
    digest: str
    owner: int
    expires_at: AwareDatetime
    allowed_networks: tuple[str, ...] = ()
    _networks: tuple[IPv4Network | IPv6Network, ...] = PrivateAttr(default=())

    def model_post_init(self, _context: Any) -> None:
        self._networks = tuple(ipaddress.ip_network(n, strict=False) for n in self.allowed_networks)

    def allows(self, address: str) -> bool:
        """Whether ``address`` (already normalised) may use the token."""
        if not self._networks:
            return True
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return False
        return any(ip in network for network in self._networks)


class MonitoringSettings(_Model):
    enabled: bool = False
    port: int = Field(DEFAULT_RELAY_PORT, ge=1, le=65535)
    rate: str = '600/min'
    tokens: tuple[RelayToken, ...] = ()
    _by_prefix: dict[str, RelayToken] = PrivateAttr(default_factory=dict)

    @field_validator('rate')
    @classmethod
    def _valid_rate(cls, value: str) -> str:
        parse_rate(value)
        return value

    def model_post_init(self, _context: Any) -> None:
        self._by_prefix = {token.prefix: token for token in self.tokens}

    @property
    def limit(self) -> tuple[int, int]:
        """(requests, seconds) each token may make."""
        return parse_rate(self.rate)

    def token(self, prefix: str) -> RelayToken | None:
        return self._by_prefix.get(prefix)

    @property
    def owners(self) -> frozenset[int]:
        return frozenset(token.owner for token in self.tokens)


class Device(_Model):
    id: int
    ip: str
    push_mode: str = PUSH_OFF
    filename_pattern: str = ''


class VaultKey(_Model):
    kid: str
    public_key: str


class ReceiverConfig(_Model):
    """What to listen for and whom to accept. The default listens for nothing."""

    bind_address: str = ''
    max_file_size: int = Field(DEFAULT_MAX_FILE_SIZE, ge=1)
    ssh: SshSettings = SshSettings()
    tftp: TftpSettings = TftpSettings()
    monitoring: MonitoringSettings = MonitoringSettings()
    devices: tuple[Device, ...] = ()
    encryption: VaultKey | None = None
    _by_address: dict[str, Device] = PrivateAttr(default_factory=dict)

    def model_post_init(self, _context: Any) -> None:
        self._by_address = {normalise_address(d.ip): d for d in self.devices}

    def device_for(self, address: str) -> Device | None:
        """The push-enabled device at ``address`` (any spelling of it), if any."""
        try:
            return self._by_address.get(normalise_address(address))
        except ValueError:
            return None

    @classmethod
    def from_assignment(cls, section: dict[str, Any], identity: Identity) -> ReceiverConfig:
        """Parse an assignment's section, opening the SSH password sealed to this receiver."""
        section = dict(section)
        ssh = dict(section.get('ssh') or {})
        sealed = ssh.pop('password_sealed', None)
        if sealed is not None:
            mine = sealed.get(identity.worker_id)
            ssh['password'] = unseal(mine, identity.encryption_key) if mine else ''
        section['ssh'] = ssh
        return cls.model_validate(section)
