"""Storage driver interface.

A storage driver writes backups somewhere and reads them back. Each storage
target configured in the orchestrator names a driver and holds its settings,
validated against the driver's ``Params`` model (whose JSON schema drives
the target form in the UI; mark secrets with ``SecretStr``).

Content is opaque bytes: it may be ciphertext. A driver returns a
``storage_ref`` from ``store`` from which ``read`` returns exactly those bytes.

``shareable`` says whether several workers can serve one target (a bucket
can be; a directory on one worker's volume cannot).

Register drivers in ``devicevault_worker.storage.drivers`` or through the
``devicevault.storage`` entry point.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict


class StorageError(Exception):
    """Storing or reading failed, and retrying will not help."""


class StorageUnavailable(StorageError):
    """The storage could not be reached; worth retrying."""


class StorageParams(BaseModel):
    model_config = ConfigDict(extra='forbid')


@dataclass(frozen=True)
class BackupName:
    """How the orchestrator identifies a backup to a driver."""

    device_key: str  # stable per device, e.g. "42-core-router-01"
    job_id: str
    timestamp: str  # compact UTC, e.g. "20261023T041500Z"
    extension: str  # ".cfg" or ".bin"


class StorageDriver(ABC):
    key: ClassVar[str]
    name: ClassVar[str]
    description: ClassVar[str] = ''
    version: ClassVar[str] = '1'
    shareable: ClassVar[bool] = False
    Params: ClassVar[type[StorageParams]] = StorageParams

    @abstractmethod
    def store(self, data: bytes, name: BackupName, params: StorageParams) -> str:
        """Write ``data``; return the reference ``read`` takes."""

    @abstractmethod
    def read(self, ref: str, params: StorageParams) -> bytes: ...

    @abstractmethod
    def delete(self, ref: str, params: StorageParams) -> None: ...

    @abstractmethod
    def check(self, params: StorageParams) -> str:
        """Verify the target is usable (raise StorageError if not); return a short description."""

    @classmethod
    def describe(cls) -> dict[str, Any]:
        return {
            'key': cls.key,
            'name': cls.name,
            'description': cls.description,
            'version': cls.version,
            'shareable': cls.shareable,
            'params_schema': cls.Params.model_json_schema(),
        }

    @staticmethod
    def object_name(name: BackupName) -> str:
        """``<device_key>/<timestamp>-<job_id><ext>``: one object per backup, sorted by time."""
        return f'{name.device_key}/{name.timestamp}-{name.job_id}{name.extension}'
