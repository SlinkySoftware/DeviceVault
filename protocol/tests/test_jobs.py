import pytest

from devicevault_protocol.jobs import FAILURE_REASONS, FAILURE_UNKNOWN, failure_reason


def test_failure_reasons_are_the_agreed_set():
    assert FAILURE_REASONS == (
        'connection',
        'auth',
        'timeout',
        'command',
        'verification',
        'storage',
        'integrity',
        'push',
        'orphaned',
        'unknown',
    )


@pytest.mark.parametrize('reason', FAILURE_REASONS)
def test_known_reasons_are_kept(reason):
    assert failure_reason(reason) == reason


@pytest.mark.parametrize('value', [None, '', 'AUTH', 'disk full', 3, ['auth']])
def test_anything_else_is_unknown(value):
    assert failure_reason(value) == FAILURE_UNKNOWN
