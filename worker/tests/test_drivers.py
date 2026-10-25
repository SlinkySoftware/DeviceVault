import pytest
from netmiko import NetmikoAuthenticationException, NetmikoTimeoutException

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
        self.enabled = True

    def send_command(self, command, read_timeout):
        self.commands.append(command)
        return self.outputs[command]


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
    ('error', 'expected'),
    [
        (NetmikoAuthenticationException('bad password'), PermanentError),
        (NetmikoTimeoutException('timed out'), TransientError),
        (ConnectionRefusedError('refused'), TransientError),
    ],
)
def test_connection_errors_are_classified(netmiko, error, expected):
    netmiko({}, error=error)

    with pytest.raises(expected):
        run('cisco_ios', CREDS)


def test_missing_credentials_are_permanent(netmiko):
    netmiko({})

    with pytest.raises(PermanentError, match='password'):
        run('cisco_ios', {'username': 'admin'})


def test_drivers_advertise_their_volatile_lines():
    """The orchestrator ignores them when it summarises changes, including pushed files."""
    cisco = get_driver('cisco_ios').describe()

    assert r'! Last configuration change at' in cisco['volatile_lines']
    assert get_driver('noop').describe()['volatile_lines'] == []
