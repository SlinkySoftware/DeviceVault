"""Storage driver registry: built-in drivers plus ``devicevault.storage`` entry points."""

import importlib.metadata
import logging
from functools import cache

from .base import BackupName, StorageDriver, StorageError, StorageParams, StorageUnavailable
from .local import FilesystemDriver, GitDriver
from .s3 import S3Driver

__all__ = ['BackupName', 'StorageDriver', 'StorageError', 'StorageParams', 'StorageUnavailable', 'get_driver']

logger = logging.getLogger(__name__)

BUILTIN_DRIVERS: tuple[type[StorageDriver], ...] = (FilesystemDriver, GitDriver, S3Driver)
ENTRY_POINT_GROUP = 'devicevault.storage'


@cache
def registry() -> dict[str, type[StorageDriver]]:
    drivers = {driver.key: driver for driver in BUILTIN_DRIVERS}
    for entry_point in importlib.metadata.entry_points(group=ENTRY_POINT_GROUP):
        try:
            driver = entry_point.load()
        except Exception:
            logger.exception('failed to load storage driver %s', entry_point.name)
            continue
        if not (isinstance(driver, type) and issubclass(driver, StorageDriver)) or driver.key in drivers:
            logger.error('ignoring storage driver entry point %s', entry_point.name)
            continue
        drivers[driver.key] = driver
    return dict(sorted(drivers.items()))


def get_driver(key: str) -> type[StorageDriver] | None:
    return registry().get(key)


def list_drivers() -> list[type[StorageDriver]]:
    return list(registry().values())
