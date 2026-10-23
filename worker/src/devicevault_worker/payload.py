"""Preparing collected content for storage (encryption is added here)."""

from typing import Any


def prepare(content: bytes, job: dict[str, Any]) -> tuple[bytes, bool]:
    """Return the bytes to stage and whether they are encrypted."""
    return content, False
