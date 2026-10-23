"""Cisco IOS and IOS XE: ``show running-config``."""

from .ssh import NetmikoDriver, SshParams


class CiscoIosDriver(NetmikoDriver):
    key = 'cisco_ios'
    name = 'Cisco IOS / IOS XE'
    description = 'Reads show running-config over SSH. Set enable_secret on the credential if privileged mode needs it.'
    version = '1'
    device_type = 'cisco_ios'
    volatile_lines = (
        r'Building configuration',
        r'Current configuration :',
        r'! Last configuration change at',
        r'! NVRAM config last updated at',
        r'! No configuration change since last restart',
        r'ntp clock-period',
    )

    def commands(self, params: SshParams) -> list[str]:
        return ['show running-config']
