"""MikroTik RouterOS: ``/export`` over SSH."""

from pydantic import Field

from .ssh import NetmikoDriver, SshParams


class MikrotikExportParams(SshParams):
    show_sensitive: bool = Field(True, description='Include secrets in the export (show-sensitive)')


class MikrotikExportDriver(NetmikoDriver):
    key = 'mikrotik_ssh_export'
    name = 'MikroTik SSH Export'
    description = 'Runs /export over SSH on RouterOS to capture the full configuration.'
    version = '3'
    device_type = 'mikrotik_routeros'
    Params = MikrotikExportParams
    # The export starts with "# <date> <time> by RouterOS <version>".
    volatile_lines = (r'# .* by RouterOS ',)

    def commands(self, params: MikrotikExportParams) -> list[str]:
        return ['/export show-sensitive' if params.show_sensitive else '/export']
