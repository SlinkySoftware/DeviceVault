"""Collector driver interface.

A driver knows how to fetch one kind of device's configuration. To add one,
subclass ``CollectorDriver``, declare a ``Params`` model for any per-device
settings (its JSON schema drives the device form in the UI), and register the
class: built-ins are listed in ``devicevault_worker.drivers``; third-party
packages expose a ``devicevault.collectors`` entry point.

Drivers raise ``TransientError`` for problems worth retrying (timeouts,
unreachable device) and ``PermanentError`` for ones that are not (bad
credentials, unsupported device); anything else counts as permanent.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict


class DriverError(Exception):
    """A collection failed."""


class TransientError(DriverError):
    """The collection may succeed if retried later."""


class PermanentError(DriverError):
    """Retrying will not help."""


class DriverParams(BaseModel):
    """Per-device driver settings. Subclass to add fields."""

    model_config = ConfigDict(extra='forbid')


@dataclass(frozen=True)
class Target:
    """The device to collect from."""

    address: str
    name: str = ''
    port: int | None = None


@dataclass
class CollectionLog:
    """Structured log entries reported back with the job."""

    source: str
    entries: list[dict[str, str]] = field(default_factory=list)

    def add(self, severity: str, message: str) -> None:
        self.entries.append(
            {
                'source': self.source,
                'timestamp': datetime.now(UTC).isoformat(),
                'severity': severity,
                'message': message,
            }
        )

    def info(self, message: str) -> None:
        self.add('INFO', message)

    def warning(self, message: str) -> None:
        self.add('WARNING', message)

    def error(self, message: str) -> None:
        self.add('ERROR', message)


class CollectorDriver(ABC):
    key: ClassVar[str]
    name: ClassVar[str]
    description: ClassVar[str] = ''
    version: ClassVar[str] = '1'
    is_binary: ClassVar[bool] = False
    Params: ClassVar[type[DriverParams]] = DriverParams

    @abstractmethod
    def collect(
        self,
        target: Target,
        credentials: dict[str, Any],
        params: DriverParams,
        *,
        timeout: int,
        log: CollectionLog,
    ) -> bytes:
        """Return the device's configuration (text drivers return UTF-8 bytes)."""

    @classmethod
    def describe(cls) -> dict[str, Any]:
        """What the worker advertises to the orchestrator."""
        return {
            'key': cls.key,
            'name': cls.name,
            'description': cls.description,
            'version': cls.version,
            'is_binary': cls.is_binary,
            'params_schema': cls.Params.model_json_schema(),
        }

    @staticmethod
    def require(credentials: dict[str, Any], *names: str) -> list[str]:
        """Values of the named credential fields, or PermanentError if any is missing."""
        missing = [name for name in names if not credentials.get(name)]
        if missing:
            raise PermanentError(f'credential is missing {", ".join(missing)}')
        return [str(credentials[name]) for name in names]
