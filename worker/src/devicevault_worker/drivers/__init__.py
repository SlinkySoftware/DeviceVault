"""Collector driver registry: built-in drivers plus ``devicevault.collectors`` entry points."""

import importlib.metadata
import logging
from functools import cache

from .base import CollectorDriver
from .demo import BinaryDummyDriver, DemoConfigDriver, NoopDriver
from .mikrotik import MikrotikExportDriver

logger = logging.getLogger(__name__)

BUILTIN_DRIVERS: tuple[type[CollectorDriver], ...] = (
    NoopDriver,
    DemoConfigDriver,
    BinaryDummyDriver,
    MikrotikExportDriver,
)

ENTRY_POINT_GROUP = 'devicevault.collectors'


@cache
def registry() -> dict[str, type[CollectorDriver]]:
    drivers = {driver.key: driver for driver in BUILTIN_DRIVERS}
    for entry_point in importlib.metadata.entry_points(group=ENTRY_POINT_GROUP):
        try:
            driver = entry_point.load()
        except Exception:
            logger.exception('failed to load collector driver %s', entry_point.name)
            continue
        if not (isinstance(driver, type) and issubclass(driver, CollectorDriver)):
            logger.error('entry point %s is not a CollectorDriver', entry_point.name)
            continue
        if driver.key in drivers:
            logger.error('collector driver key %s from %s is already registered', driver.key, entry_point.name)
            continue
        drivers[driver.key] = driver
    return dict(sorted(drivers.items()))


def get_driver(key: str) -> type[CollectorDriver] | None:
    return registry().get(key)


def list_drivers() -> list[type[CollectorDriver]]:
    return list(registry().values())
