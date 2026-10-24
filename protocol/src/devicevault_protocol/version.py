"""The DeviceVault release version.

The repository's ``VERSION`` file is the source; ``make set-version`` copies it into
every package's metadata. Images install the packages, so they read the metadata;
the dev image puts the source on the path without installing it, so it reads the file.

``python -m devicevault_protocol.version`` prints it.
"""

import importlib.metadata
from functools import cache
from pathlib import Path

VERSION_FILE = Path(__file__).resolve().parents[3] / 'VERSION'


@cache
def version() -> str:
    try:
        return importlib.metadata.version('devicevault-protocol')
    except importlib.metadata.PackageNotFoundError:
        pass
    try:
        return VERSION_FILE.read_text().strip()
    except OSError:
        return '0.0.0'


if __name__ == '__main__':
    print(version())
