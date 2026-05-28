"""Helpers for parsing fixed loop intervals."""

from __future__ import annotations

import re
from datetime import timedelta


class IntervalParseError(ValueError):
    """Raised when a loop interval cannot be parsed."""


_COMPACT_INTERVAL_RE = re.compile(r"^(?P<value>\d+)(?P<unit>[smhd])$", re.IGNORECASE)
_PHRASE_INTERVAL_RE = re.compile(
    r"^(?:every\s+)?(?P<value>\d+)\s*(?P<unit>"
    r"seconds?|secs?|minutes?|mins?|hours?|hrs?|days?)$",
    re.IGNORECASE,
)

_UNIT_SECONDS = {
    "s": 1,
    "sec": 1,
    "secs": 1,
    "second": 1,
    "seconds": 1,
    "m": 60,
    "min": 60,
    "mins": 60,
    "minute": 60,
    "minutes": 60,
    "h": 3600,
    "hr": 3600,
    "hrs": 3600,
    "hour": 3600,
    "hours": 3600,
    "d": 86400,
    "day": 86400,
    "days": 86400,
}


def parse_interval(value: str) -> timedelta:
    """Parse a fixed loop interval such as ``5m`` or ``every 2 hours``."""
    normalized = value.strip().lower()
    if not normalized:
        raise IntervalParseError("interval cannot be empty")

    match = _COMPACT_INTERVAL_RE.fullmatch(normalized)
    if match is None:
        match = _PHRASE_INTERVAL_RE.fullmatch(normalized)
    if match is None:
        raise IntervalParseError(
            "interval must look like '5m', '2h', or 'every 10 minutes'"
        )

    amount = int(match.group("value"))
    if amount <= 0:
        raise IntervalParseError("interval must be greater than zero")

    unit = match.group("unit").lower()
    seconds = amount * _UNIT_SECONDS[unit]
    try:
        return timedelta(seconds=seconds)
    except OverflowError as exc:
        raise IntervalParseError("interval is too large") from exc
