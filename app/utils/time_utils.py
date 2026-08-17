"""Tiny datetime helper. `datetime.utcnow()` is deprecated as of Python
3.12; the replacement `datetime.now(timezone.utc)` returns a
timezone-aware value, but our SQLite DateTime columns store naive
values, so we strip the tzinfo back off after using the non-deprecated
API — same on-disk behavior, no deprecation warning."""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
