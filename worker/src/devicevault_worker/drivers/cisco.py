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
    rejected_output = (
        r'% ?Invalid input detected',
        r'% ?Incomplete command',
        r'% ?Ambiguous command',
        r'% ?Unknown command',
        r'% ?Authorization failed',
    )
    # Type 7 is reversible, so its values are decoded before hashing; types 5, 8 and 9
    # are salted hashes and are tokenised as written. A type digit before the value is
    # skipped; a bare number after ``key`` is a key id, not a secret.
    secret_lines = (
        (r'^enable password (?:level \d+ )?7 (\S+)', 'cisco7'),
        r'^enable (?:secret|password) (?:level \d+ )?(?:\d+ )?(\S+)',
        (r'^username \S+ .*?(?:secret|password) 7 (\S+)', 'cisco7'),
        r'^username \S+ .*?(?:secret|password) (?:\d+ )?(\S+)',
        r'^snmp-server community (\S+)',
        r'^snmp-server host \S+ (?:(?:informs|traps) )?(?:version (?:1|2c) )?(?!version )(\S+)',
        r'^snmp-server user \S+ \S+ .*?\bauth \S+ (\S+)(?: priv (?:3des|des|aes(?: \d+)?) (\S+))?',
        (r'^password 7 (\S+)', 'cisco7'),
        r'^password (?:\d+ )?(\S+)',
        (r'^key-string 7 (\S+)', 'cisco7'),
        r'^key-string (?:\d+ )?(\S+)',
        (r'^(?:(?:tacacs|radius)-server (?:host \S+ .*?)?)?key 7 (\S+)', 'cisco7'),
        r'^(?:(?:tacacs|radius)-server (?:host \S+ .*?)?)?key (?:[06] )?(?!\d+$)(\S+)',
        r'^server-private \S+ .*?key (?:[067] )?(\S+)',
        r'^crypto isakmp key (?:[06] )?(\S+)',
        r'^pre-shared-key (?:local |remote )?(?:[06] )?(\S+)',
        (r'^neighbor \S+ password 7 (\S+)', 'cisco7'),
        r'^neighbor \S+ password (?:\d+ )?(\S+)',
        (r'^ip ospf (?:authentication-key|message-digest-key \d+ md5) 7 (\S+)', 'cisco7'),
        r'^ip ospf (?:authentication-key|message-digest-key \d+ md5) (?:\d+ )?(\S+)',
        (r'^ntp authentication-key \d+ md5 (\S+) 7$', 'cisco7'),
        r'^ntp authentication-key \d+ md5 (\S+)',
    )

    def commands(self, params: SshParams) -> list[str]:
        return ['show running-config']
