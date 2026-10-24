"""Every package carries the release version from the repository's VERSION file."""

import json
import re
import tomllib

import pytest

from devicevault_protocol.version import VERSION_FILE, version

ROOT = VERSION_FILE.parent
RELEASE = VERSION_FILE.read_text().strip()


def test_version_file_is_semver():
    assert re.fullmatch(r'\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?', RELEASE)


def test_version_reads_the_release():
    assert version() == RELEASE


@pytest.mark.parametrize('package', ['protocol', 'worker', 'receiver', 'orchestrator'])
def test_python_packages_match(package):
    pyproject = tomllib.loads((ROOT / package / 'pyproject.toml').read_text())

    assert pyproject['project']['version'] == RELEASE, 'run make set-version V=' + RELEASE


@pytest.mark.parametrize('path', ['frontend/package.json', 'frontend/package-lock.json'])
def test_frontend_matches(path):
    manifest = json.loads((ROOT / path).read_text())

    assert manifest['version'] == RELEASE, 'run make set-version V=' + RELEASE
