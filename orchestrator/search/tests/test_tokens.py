import pytest

from core import keys
from core.workers import _secret_lines
from search.tokens import TOKEN_RE, compile_patterns, decode_cisco7, token, tokenise_line, tokenise_text

from .conftest import CISCO_SECRETS

PATTERNS = compile_patterns(CISCO_SECRETS)


def test_cisco_type_7_is_decoded():
    assert decode_cisco7('0822455D0A16') == 'cisco'
    assert decode_cisco7('xx22') is None
    assert decode_cisco7('082') is None


def test_a_secret_value_becomes_a_token_and_the_rest_of_the_line_stays(db):
    line = tokenise_line('snmp-server community public RO', PATTERNS)

    assert line == f'snmp-server community {token("public")} RO'
    assert TOKEN_RE.search(line) and 'public' not in line


def test_indentation_and_case_are_kept(db):
    assert (
        tokenise_line('  SNMP-SERVER COMMUNITY Public RO', PATTERNS) == f'  SNMP-SERVER COMMUNITY {token("Public")} RO'
    )


def test_a_type_7_value_and_its_plaintext_give_the_same_token(db):
    encoded = tokenise_line('username ops password 7 0822455D0A16', PATTERNS)
    plain = tokenise_line('username ops password cisco', PATTERNS)

    assert encoded.endswith(token('cisco')) and plain.endswith(token('cisco'))


def test_only_the_first_matching_pattern_applies(db):
    """The type-7 pattern wins, so the general one does not also tokenise the "7"."""
    assert (
        tokenise_line('username ops password 7 0822455D0A16', PATTERNS) == f'username ops password 7 {token("cisco")}'
    )


def test_a_token_is_not_tokenised_again(db):
    line = tokenise_line('snmp-server community public RO', PATTERNS)

    assert tokenise_line(line, PATTERNS) == line


def test_lines_without_secrets_are_unchanged(db):
    text = 'hostname edge\ninterface Gi0/1\n'

    assert tokenise_text(text, PATTERNS) == text
    assert tokenise_text('snmp-server community x', compile_patterns([])) == 'snmp-server community x'


def test_every_match_of_the_pattern_is_tokenised(db):
    patterns = compile_patterns([{'pattern': r'(?:^|\s)(?:password|secret)=(\S+)', 'encoding': None}])

    assert (
        tokenise_line('add password=a secret=b name=c', patterns)
        == f'add password={token("a")} secret={token("b")} name=c'
    )


def test_tokens_depend_on_the_key(db):
    assert token('public', b'k' * 32) != token('public', b'j' * 32)


def test_the_token_key_is_derived_and_follows_the_current_data_key(settings):
    keys._data_key_ring.cache_clear()
    keys.search_token_key.cache_clear()
    try:
        kid, key = keys.search_token_key()
        assert kid == 'test' and len(key) == 32 and key not in keys._data_key_ring()[1].values()

        settings.DEVICEVAULT_DATA_KEYS = (
            'next=' + 'bmV4dC1kYXRhLWtleS0zMi1ieXRlcy1sb25nISEhISE=,' + settings.DEVICEVAULT_DATA_KEYS
        )
        keys._data_key_ring.cache_clear()
        keys.search_token_key.cache_clear()
        assert keys.search_token_key()[0] == 'next' and keys.search_token_key()[1] != key
    finally:
        keys._data_key_ring.cache_clear()
        keys.search_token_key.cache_clear()
        keys.data_keys.cache_clear()


def test_the_fingerprint_changes_with_the_patterns():
    assert PATTERNS.fingerprint != compile_patterns(CISCO_SECRETS[:1]).fingerprint
    assert PATTERNS.fingerprint == compile_patterns(list(CISCO_SECRETS)).fingerprint


@pytest.mark.parametrize(
    ('advertised', 'kept'),
    [
        ([{'pattern': r'^key (\S+)', 'encoding': 'cisco7'}], [{'pattern': r'^key (\S+)', 'encoding': 'cisco7'}]),
        ([{'pattern': r'^key (\S+)', 'encoding': 'rot13'}], [{'pattern': r'^key (\S+)', 'encoding': None}]),
        ([{'pattern': r'^key \S+'}], []),
        ([{'pattern': r'^key ((\S+)'}], []),
        ([{'pattern': 'x' * 300 + '(a)'}], []),
        (['^key (\\S+)'], []),
        ('nope', []),
    ],
)
def test_advertised_secret_lines_are_validated(advertised, kept):
    assert _secret_lines(advertised) == kept
