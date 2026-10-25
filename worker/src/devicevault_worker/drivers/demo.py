"""Demonstration drivers that need no real device."""

import hashlib
from datetime import UTC, datetime
from typing import Any

from pydantic import Field

from .base import CollectionLog, CollectorDriver, DriverParams, Target


class NoopDriver(CollectorDriver):
    key = 'noop'
    name = 'No Operation'
    description = 'Returns an empty configuration; for testing the pipeline.'

    def collect(self, target, credentials, params, *, timeout, log):
        log.info('noop driver: nothing collected')
        return b''


class DemoConfigParams(DriverParams):
    hostname: str | None = Field(None, description='Hostname to put in the configuration (default: device name)')
    interfaces: int = Field(4, ge=1, le=48, description='Number of interfaces to generate')


class DemoConfigDriver(CollectorDriver):
    """A realistic-looking text configuration that changes slightly every hour."""

    key = 'demo_config'
    name = 'Demo Configuration'
    description = 'Generates a router-style text configuration that changes hourly; for trying out comparisons.'
    Params = DemoConfigParams
    # Config search indexes the community only as a token.
    secret_lines = (r'^snmp-server community (\S+)',)

    def collect(self, target: Target, credentials: dict[str, Any], params, *, timeout: int, log: CollectionLog):
        now = datetime.now(UTC)
        hostname = params.hostname or target.name or 'demo-router'
        # Deterministic per hour, so consecutive backups within an hour are identical.
        seed = int(hashlib.sha256(f'{hostname}{now:%Y%m%d%H}'.encode()).hexdigest(), 16)
        lines = [
            '! demo configuration',
            f'hostname {hostname}',
            'service timestamps log datetime msec',
            '!',
        ]
        for index in range(params.interfaces):
            state = 'no shutdown' if (seed >> index) & 1 else 'shutdown'
            lines += [
                f'interface GigabitEthernet0/{index}',
                f' description link-{index}',
                f' ip address 10.{index}.0.1 255.255.255.252',
                f' {state}',
                '!',
            ]
        lines += [
            f'ntp server 10.255.0.{(seed % 3) + 1}',
            f'snmp-server location rack-{seed % 20}',
            'snmp-server community public RO',
            'end',
            '',
        ]
        log.info(f'generated {len(lines)} lines for {hostname}')
        return '\n'.join(lines).encode('utf-8')


class BinaryDummyDriver(CollectorDriver):
    key = 'binary_dummy'
    name = 'Binary Dummy (Demo)'
    description = 'Returns a 1 MB binary blob; for testing binary backups.'
    is_binary = True

    def collect(self, target, credentials, params, *, timeout, log):
        header = b'\xff\xfeFIRMWARE_HEADER_DEMO'
        blob = header + bytes(1024 * 1024 - len(header))
        log.info(f'generated {len(blob)} bytes of binary data')
        return blob
