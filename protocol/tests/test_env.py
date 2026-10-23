import pytest

from devicevault_protocol.env import ConfigError, env_bool, env_int, env_list, env_map, env_str


def test_env_str_prefers_file_over_value(monkeypatch, tmp_path):
    secret = tmp_path / 'secret'
    secret.write_text('from-file\n')
    monkeypatch.setenv('DV_TEST', 'from-env')
    monkeypatch.setenv('DV_TEST_FILE', str(secret))

    assert env_str('DV_TEST') == 'from-file'


def test_env_str_unreadable_file_is_an_error(monkeypatch, tmp_path):
    monkeypatch.setenv('DV_TEST_FILE', str(tmp_path / 'missing'))

    with pytest.raises(ConfigError, match='DV_TEST_FILE'):
        env_str('DV_TEST')


def test_env_str_required(monkeypatch):
    monkeypatch.delenv('DV_TEST', raising=False)

    with pytest.raises(ConfigError, match='DV_TEST must be set'):
        env_str('DV_TEST', required=True)


@pytest.mark.parametrize(('raw', 'expected'), [('true', True), ('ON', True), ('0', False), ('no', False)])
def test_env_bool(monkeypatch, raw, expected):
    monkeypatch.setenv('DV_TEST', raw)

    assert env_bool('DV_TEST', not expected) is expected


def test_env_bool_rejects_garbage(monkeypatch):
    monkeypatch.setenv('DV_TEST', 'maybe')

    with pytest.raises(ConfigError):
        env_bool('DV_TEST', False)


def test_env_int_minimum(monkeypatch):
    monkeypatch.setenv('DV_TEST', '0')

    with pytest.raises(ConfigError, match='>= 1'):
        env_int('DV_TEST', 5, minimum=1)


def test_env_list_strips_blanks(monkeypatch):
    monkeypatch.setenv('DV_TEST', ' a, ,b ,')

    assert env_list('DV_TEST') == ['a', 'b']


def test_env_map_keeps_base64_padding(monkeypatch):
    monkeypatch.setenv('DV_TEST', 'mk-1=AAAA==,mk-2=BBBB')

    assert env_map('DV_TEST') == {'mk-1': 'AAAA==', 'mk-2': 'BBBB'}


def test_env_map_rejects_missing_value(monkeypatch):
    monkeypatch.setenv('DV_TEST', 'mk-1')

    with pytest.raises(ConfigError):
        env_map('DV_TEST')
