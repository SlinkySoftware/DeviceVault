"""Running config searches (ARCHITECTURE.md section 7.2).

The database narrows the candidate documents (on PostgreSQL with the trigram
index; SQLite scans), then each candidate's lines are matched here. Regexes are
RE2, which runs in linear time, so a user's pattern cannot hang the API.
"""

import time
from dataclasses import dataclass

import re2
from django.db import DatabaseError, OperationalError, connection, transaction
from django.db.models import Q

from accounts import access
from core.workers import driver_catalogue
from search.indexing import driver_patterns
from search.models import SearchDocument
from search.tokens import tokenise_line

MODE_TEXT = 'text'
MODE_REGEX = 'regex'
MODES = (MODE_TEXT, MODE_REGEX)

MAX_QUERY_LENGTH = 256
MIN_TEXT_LENGTH = 3
MAX_DEVICES = 200
MAX_LINES = 20
STATEMENT_TIMEOUT_MS = 5000
# SQLite has no statement timeout; the line matching stops after this.
SCAN_SECONDS = 10


class SearchError(ValueError):
    """The search cannot be run as asked (the message says why)."""


@dataclass
class Search:
    query: str
    mode: str
    device_group: int | None = None
    driver: str | None = None


def _escape_like(value: str) -> str:
    return value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def postgres_regex(pattern: str) -> str:
    """An RE2 pattern in PostgreSQL's syntax, as far as candidate filtering needs it.

    PostgreSQL spells word boundaries ``\\y`` and has no named groups; anything else it
    rejects means no candidate filter rather than an error (RE2 still decides).
    """
    escapes = {'\\b': '\\y', '\\B': '\\Y', '\\A': '^', '\\z': '$'}
    out, index = [], 0
    while index < len(pattern):
        if pattern[index] == '\\' and index + 1 < len(pattern):
            pair = pattern[index : index + 2]
            out.append(escapes.get(pair, pair))
            index += 2
        elif pattern.startswith('(?P<', index) and '>' in pattern[index:]:
            out.append('(')
            index = pattern.index('>', index) + 1
        else:
            out.append(pattern[index])
            index += 1
    return ''.join(out)


def _postgres_accepts(pattern: str) -> bool:
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SELECT '' ~* %s", [pattern])
        return True
    except DatabaseError:
        return False


def compile_regex(pattern: str):
    options = re2.Options()
    options.case_sensitive = False
    options.log_errors = False
    try:
        return re2.compile(pattern, options)
    except re2.error as exc:
        message = exc.args[0].decode() if exc.args and isinstance(exc.args[0], bytes) else str(exc)
        raise SearchError(f'Invalid regular expression: {message}') from exc


def validate(search: Search) -> None:
    if search.mode not in MODES:
        raise SearchError(f'Unknown search mode "{search.mode}".')
    if '\n' in search.query or '\r' in search.query:
        raise SearchError('Search for one line at a time.')
    if len(search.query) > MAX_QUERY_LENGTH:
        raise SearchError(f'Searches are at most {MAX_QUERY_LENGTH} characters.')
    if search.mode == MODE_TEXT and len(search.query.strip()) < MIN_TEXT_LENGTH:
        raise SearchError(f'Search for at least {MIN_TEXT_LENGTH} characters.')
    if search.mode == MODE_REGEX and not search.query:
        raise SearchError('Enter a regular expression.')


def visible_documents(user, search: Search):
    """The searchable documents of devices whose contents ``user`` may see, with the search's filters."""
    documents = SearchDocument.objects.filter(
        skipped='', device__in=access.devices_for(user, 'view_contents')
    ).select_related('device__device_group', 'job')
    if search.device_group is not None:
        documents = documents.filter(device__device_group_id=search.device_group)
    if search.driver:
        documents = documents.filter(driver=search.driver)
    return documents


def text_needles(documents, query: str) -> dict[str, list[str]]:
    """The query as each driver's documents hold it (secret values tokenised), mapped to those drivers."""
    catalogue = driver_catalogue()
    needles: dict[str, list[str]] = {}
    for driver in documents.values_list('driver', flat=True).distinct():
        needles.setdefault(tokenise_line(query, driver_patterns(driver, catalogue)), []).append(driver)
    return needles


def recorded_query(search: Search, needles: dict[str, list[str]] | None) -> str:
    """The query as the audit log keeps it: secret values typed into a text search are tokenised."""
    if search.mode == MODE_TEXT and needles:
        return next((needle for needle in needles if needle != search.query), search.query)
    return search.query


def _matcher(search: Search, needles: dict[str, list[str]] | None):
    """A function of (document, line) telling whether the line matches."""
    if search.mode == MODE_REGEX:
        regex = compile_regex(search.query)
        return lambda document, line: regex.search(line) is not None
    lowered = {driver: needle.lower() for needle, drivers in (needles or {}).items() for driver in drivers}
    return lambda document, line: lowered.get(document.driver, '\0') in line.lower()


def _candidates(documents, search: Search, needles: dict[str, list[str]] | None):
    if search.mode == MODE_TEXT:
        if not needles:
            return documents.none()
        condition = Q()
        for needle, drivers in needles.items():
            condition |= Q(driver__in=drivers, text__dv_like=f'%{_escape_like(needle)}%')
        return documents.filter(condition)
    if connection.vendor == 'postgresql':
        # Newline-sensitive, so "." and "^"/"$" work per line as RE2 does here.
        pattern = '(?n)' + postgres_regex(search.query)
        if _postgres_accepts(pattern):
            return documents.filter(text__dv_iregex=pattern)
    return documents


def run(user, search: Search) -> tuple[dict, str]:
    """Search the latest backups of the devices ``user`` may read: the response and the query to audit.

    Raises ``SearchError``.
    """
    validate(search)
    if search.mode == MODE_REGEX:
        compile_regex(search.query)
    documents = visible_documents(user, search)
    needles = text_needles(documents, search.query) if search.mode == MODE_TEXT else None
    matches = _matcher(search, needles)
    results, truncated, timed_out = [], False, False
    deadline = time.monotonic() + SCAN_SECONDS
    try:
        with transaction.atomic():
            if connection.vendor == 'postgresql':
                with connection.cursor() as cursor:
                    cursor.execute(f'SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}')
            candidates = _candidates(documents, search, needles).order_by('device__name', 'device_id')
            for document in candidates.iterator(chunk_size=50):
                if time.monotonic() > deadline:
                    timed_out = True
                    break
                lines = [
                    (number, line)
                    for number, line in enumerate(document.text.split('\n'), start=1)
                    if matches(document, line)
                ]
                if not lines:
                    continue
                if len(results) == MAX_DEVICES:
                    truncated = True
                    break
                results.append(_result(document, lines))
    except OperationalError as exc:
        raise SearchError('The search took too long; make it more specific or filter it.') from exc
    response = {
        'mode': search.mode,
        'query': search.query,
        'results': results,
        'truncated': truncated,
        'timed_out': timed_out,
        'searched_devices': documents.count(),
    }
    return response, recorded_query(search, needles)


def _result(document: SearchDocument, lines: list[tuple[int, str]]) -> dict:
    device = document.device
    group = device.device_group
    return {
        'device': device.pk,
        'device_name': device.name,
        'device_group': group.pk if group else None,
        'device_group_name': group.name if group else None,
        'driver': document.driver,
        'job': str(document.job_id),
        'backup_at': document.job.created_at,
        'indexed_at': document.indexed_at,
        'match_count': len(lines),
        'lines': [{'number': number, 'text': text} for number, text in lines[:MAX_LINES]],
    }
