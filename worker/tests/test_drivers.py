import re
import socket

import pytest
from netmiko import NetmikoAuthenticationException, NetmikoTimeoutException
from netmiko.exceptions import ReadTimeout
from paramiko.ssh_exception import SSHException

from devicevault_worker.drivers import get_driver
from devicevault_worker.drivers.base import CollectionLog, PermanentError, Target, TransientError

CISCO_OUTPUT = """Building configuration...

Current configuration : 1234 bytes
!
! Last configuration change at 04:15:01 AEDT Fri Oct 23 2026 by admin
! NVRAM config last updated at 04:15:09 AEDT Fri Oct 23 2026 by admin
!
version 17.9
hostname edge-01
ntp clock-period 36028797018963968
!
end
"""

MIKROTIK_OUTPUT = """# 2026-10-23 04:15:01 by RouterOS 7.16.1
# software id = ABCD-1234
/system identity
set name=edge-01
"""


class FakeConnection:
    enable_error = None

    def __init__(self, outputs, error=None, **kwargs):
        self.kwargs = kwargs
        self.outputs = outputs
        self.error = error
        self.commands = []
        self.enabled = False

    def __enter__(self):
        if self.error:
            raise self.error
        return self

    def __exit__(self, *exc):
        return False

    def enable(self):
        if self.enable_error:
            raise self.enable_error
        self.enabled = True

    def send_command(self, command, read_timeout):
        self.commands.append(command)
        output = self.outputs[command]
        if isinstance(output, BaseException):
            raise output
        return output


@pytest.fixture
def netmiko(monkeypatch):
    """Replace Netmiko's ConnectHandler; returns the connections made."""
    made = []

    def install(outputs, error=None):
        def connect(**kwargs):
            made.append(FakeConnection(outputs, error, **kwargs))
            return made[-1]

        monkeypatch.setattr('devicevault_worker.drivers.ssh.ConnectHandler', connect)
        return made

    return install


def run(key, credentials, **params):
    driver = get_driver(key)
    return driver().collect(
        Target(address='192.0.2.1', name='edge-01'),
        credentials,
        driver.Params.model_validate(params),
        timeout=10,
        log=CollectionLog(source=key),
    )


CREDS = {'username': 'admin', 'password': 'pw'}


def test_cisco_running_config_without_volatile_lines(netmiko):
    netmiko({'show running-config': CISCO_OUTPUT})

    output = run('cisco_ios', CREDS).decode()

    assert output == '!\n!\nversion 17.9\nhostname edge-01\n!\nend\n'


def test_cisco_enters_enable_mode_only_with_a_secret(netmiko):
    made = netmiko({'show running-config': CISCO_OUTPUT})

    run('cisco_ios', {**CREDS, 'enable_secret': 'en'})
    run('cisco_ios', CREDS)

    assert [c.enabled for c in made] == [True, False]
    assert made[0].kwargs['device_type'] == 'cisco_ios' and made[0].kwargs['secret'] == 'en'


def test_volatile_lines_can_be_kept(netmiko):
    netmiko({'show running-config': CISCO_OUTPUT})

    assert 'Last configuration change' in run('cisco_ios', CREDS, strip_volatile=False).decode()


def test_mikrotik_export(netmiko):
    made = netmiko({'/export show-sensitive': MIKROTIK_OUTPUT, '/export': MIKROTIK_OUTPUT})

    output = run('mikrotik_ssh_export', CREDS, port=2222).decode()
    run('mikrotik_ssh_export', CREDS, show_sensitive=False)

    assert output.startswith('# software id')
    assert [c.commands for c in made] == [['/export show-sensitive'], ['/export']]
    assert made[0].kwargs['port'] == 2222 and made[0].kwargs['device_type'] == 'mikrotik_routeros'


@pytest.mark.parametrize(
    ('error', 'expected', 'reason'),
    [
        (NetmikoAuthenticationException('bad password'), PermanentError, 'auth'),
        (NetmikoTimeoutException('TCP connection to device failed'), TransientError, 'connection'),
        (ConnectionRefusedError('refused'), TransientError, 'connection'),
        (socket.gaierror('Name or service not known'), TransientError, 'connection'),
        (SSHException('Error reading SSH protocol banner'), TransientError, 'connection'),
    ],
)
def test_connection_errors_are_classified(netmiko, error, expected, reason):
    netmiko({}, error=error)

    with pytest.raises(expected) as raised:
        run('cisco_ios', CREDS)

    assert raised.value.reason == reason


@pytest.mark.parametrize('error', [ReadTimeout('pattern not detected'), EOFError(), OSError('socket closed')])
def test_a_device_that_stops_answering_mid_session_times_out(netmiko, error):
    netmiko({'show running-config': error})

    with pytest.raises(TransientError, match='stopped responding') as raised:
        run('cisco_ios', CREDS)

    assert raised.value.reason == 'timeout'


def test_a_refused_enable_is_an_auth_failure(netmiko):
    made = netmiko({'show running-config': CISCO_OUTPUT})
    FakeConnection.enable_error = ValueError('Failed to enter enable mode.')
    try:
        with pytest.raises(PermanentError, match='enable mode refused') as raised:
            run('cisco_ios', {**CREDS, 'enable_secret': 'wrong'})
    finally:
        FakeConnection.enable_error = None

    assert raised.value.reason == 'auth' and made[0].commands == []


@pytest.mark.parametrize(
    ('key', 'command', 'output'),
    [
        (
            'cisco_ios',
            'show running-config',
            "show running-config\n          ^\n% Invalid input detected at '^' marker.\n",
        ),
        ('cisco_ios', 'show running-config', '% Authorization failed.\n'),
        ('mikrotik_ssh_export', '/export show-sensitive', 'bad command name show-sensitive (line 1 column 9)\n'),
    ],
)
def test_rejected_commands_are_command_failures(netmiko, key, command, output):
    netmiko({command: output})

    with pytest.raises(PermanentError, match='rejected') as raised:
        run(key, CREDS)

    assert raised.value.reason == 'command'


def test_rejection_text_inside_the_configuration_is_not_a_rejection(netmiko):
    banner = CISCO_OUTPUT.replace('version 17.9\n', 'version 17.9\nbanner motd ^\n% Invalid input detected\n^\n')
    netmiko({'show running-config': banner})

    assert '% Invalid input detected' in run('cisco_ios', CREDS).decode()


def test_missing_credentials_are_permanent(netmiko):
    netmiko({})

    with pytest.raises(PermanentError, match='password') as raised:
        run('cisco_ios', {'username': 'admin'})

    assert raised.value.reason == 'auth'


def test_driver_errors_default_to_unknown_and_reject_unknown_reasons():
    assert TransientError('x').reason == 'unknown'
    assert PermanentError('x', reason='nonsense').reason == 'unknown'
    assert PermanentError('x', reason='storage').reason == 'storage'


def test_drivers_advertise_their_volatile_lines():
    """The orchestrator ignores them when it summarises changes, including pushed files."""
    cisco = get_driver('cisco_ios').describe()

    assert r'! Last configuration change at' in cisco['volatile_lines']
    assert get_driver('noop').describe()['volatile_lines'] == []


def first_secrets(key, line):
    """The secret values the first matching ``secret_lines`` pattern captures, as the orchestrator applies them."""
    for entry in get_driver(key).describe()['secret_lines']:
        matches = list(re.finditer(entry['pattern'], line.lstrip(), re.IGNORECASE))
        if matches:
            return [(value, entry['encoding']) for match in matches for value in match.groups() if value]
    return []


@pytest.mark.parametrize(
    ('line', 'secrets'),
    [
        ('snmp-server community public RO', [('public', None)]),
        ('snmp-server host 10.0.0.9 version 2c s3cret', [('s3cret', None)]),
        ('snmp-server host 10.0.0.9 version 3 priv monitor', []),
        ('enable secret 9 $9$abc$def', [('$9$abc$def', None)]),
        ('enable password 7 0822455D0A16', [('0822455D0A16', 'cisco7')]),
        ('username admin privilege 15 secret 9 $9$xyz', [('$9$xyz', None)]),
        ('username ops password 7 0822455D0A16', [('0822455D0A16', 'cisco7')]),
        (' password 7 0822455D0A16', [('0822455D0A16', 'cisco7')]),
        (' key-string 7 0822455D0A16', [('0822455D0A16', 'cisco7')]),
        (' key 1', []),
        (' key 7 0822455D0A16', [('0822455D0A16', 'cisco7')]),
        ('tacacs-server key s3cret', [('s3cret', None)]),
        ('crypto isakmp key 6 Vpn!Key address 192.0.2.1', [('Vpn!Key', None)]),
        (' neighbor 192.0.2.2 password 7 0822455D0A16', [('0822455D0A16', 'cisco7')]),
        ('ntp authentication-key 1 md5 104D000A0618 7', [('104D000A0618', 'cisco7')]),
        ('interface GigabitEthernet0/1', []),
    ],
)
def test_cisco_secret_lines(line, secrets):
    assert first_secrets('cisco_ios', line) == secrets


def test_mikrotik_secret_lines():
    line = 'add name=vpn password="pa ss\\"word" secret=abc123 comment=x'

    assert first_secrets('mikrotik_ssh_export', line) == [('"pa ss\\"word"', None), ('abc123', None)]
    assert first_secrets('mikrotik_ssh_export', 'set enabled=yes ipsec-secret=l2tp use-ipsec=yes') == [('l2tp', None)]
    assert first_secrets('mikrotik_ssh_export', 'add private-key="abc=" public-key="def="') == [('"abc="', None)]
    assert get_driver('noop').describe()['secret_lines'] == []
