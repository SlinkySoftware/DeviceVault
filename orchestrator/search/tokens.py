"""Secret tokens: how config search indexes secret values without holding them.

Collector drivers declare ``secret_lines`` (validated in ``core.workers``): regexes
whose groups are secret values, each with an optional reversible encoding. Every
captured value becomes ``{{secret:<hex>}}``, an HMAC of the (decoded) value keyed
from the current data key (``core.keys.search_token_key``). Queries go through the
same patterns on the server, so a line typed with its secret in it, or a bare
secret value, finds the lines that hold it, while the index shows only which
devices share a secret.

Patterns are searched case-insensitively in the line with its leading spaces
removed, and the first pattern that matches a line is the only one applied to it.
"""

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from functools import cache

from core import keys

TOKEN_RE = re.compile(r'\{\{secret:[0-9a-f]{32}\}\}')
# Bump when tokenising changes, so the catch-up pass rebuilds every document.
TOKEN_VERSION = 1

# Cisco type 7: a Vigenère-style XOR with this fixed key, from the offset in the first two digits.
_CISCO7_KEY = b'dsfd;kfoA,.iyewrkldJKDHSUBsgvca69834ncxv9873254k;fg87'


def decode_cisco7(value: str) -> str | None:
    """The plaintext of a Cisco type 7 value, or None if it is not one."""
    if len(value) < 4 or len(value) % 2 or not value[:2].isdigit():
        return None
    try:
        data = bytes.fromhex(value[2:])
    except ValueError:
        return None
    seed = int(value[:2])
    plain = bytes(byte ^ _CISCO7_KEY[(seed + index) % len(_CISCO7_KEY)] for index, byte in enumerate(data))
    try:
        return plain.decode('utf-8')
    except UnicodeDecodeError:
        return None


DECODERS = {'cisco7': decode_cisco7}


@dataclass(frozen=True)
class SecretPattern:
    regex: re.Pattern
    encoding: str | None


@dataclass(frozen=True)
class SecretPatterns:
    patterns: tuple[SecretPattern, ...]
    fingerprint: str


@cache
def _compiled(spec: str) -> SecretPatterns:
    entries = json.loads(spec)
    patterns = tuple(SecretPattern(re.compile(e['pattern'], re.IGNORECASE), e.get('encoding')) for e in entries)
    fingerprint = hashlib.sha256(f'{TOKEN_VERSION}:{spec}'.encode()).hexdigest()
    return SecretPatterns(patterns, fingerprint)


def compile_patterns(entries: list[dict] | None) -> SecretPatterns:
    """A driver's validated ``secret_lines`` (from the catalogue), compiled, with their fingerprint."""
    return _compiled(json.dumps(entries or [], sort_keys=True))


def token(value: str, key: bytes | None = None) -> str:
    """The token standing for secret ``value``."""
    key = key if key is not None else keys.search_token_key()[1]
    digest = hmac.new(key, value.encode('utf-8'), hashlib.sha256).hexdigest()[:32]
    return f'{{{{secret:{digest}}}}}'


def _token_for(value: str, encoding: str | None, key: bytes) -> str:
    if TOKEN_RE.fullmatch(value):
        return value  # already a token (a result line pasted back as a query)
    decoder = DECODERS.get(encoding or '')
    decoded = decoder(value) if decoder else None
    return token(decoded if decoded is not None else value, key)


def tokenise_line(line: str, patterns: SecretPatterns, key: bytes | None = None) -> str:
    """``line`` with the secret values the first matching pattern finds replaced by tokens."""
    if not patterns.patterns:
        return line
    stripped = line.lstrip()
    indent = line[: len(line) - len(stripped)]
    for pattern in patterns.patterns:
        spans = [
            (match.start(group), match.end(group))
            for match in pattern.regex.finditer(stripped)
            for group in range(1, pattern.regex.groups + 1)
            if match.start(group) < match.end(group)
        ]
        if not spans:
            continue
        key = key if key is not None else keys.search_token_key()[1]
        parts, last = [], 0
        for start, end in sorted(set(spans)):
            if start < last:
                continue  # a group nested in another one is part of that secret
            parts += [stripped[last:start], _token_for(stripped[start:end], pattern.encoding, key)]
            last = end
        return indent + ''.join(parts) + stripped[last:]
    return line


def tokenise_text(text: str, patterns: SecretPatterns) -> str:
    if not patterns.patterns:
        return text
    key = keys.search_token_key()[1]
    return '\n'.join(tokenise_line(line, patterns, key) for line in text.split('\n'))
