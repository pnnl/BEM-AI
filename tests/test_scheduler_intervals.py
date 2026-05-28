from __future__ import annotations

from datetime import timedelta

import pytest

from automa_ai.scheduler import IntervalParseError, parse_interval


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("5m", timedelta(minutes=5)),
        ("2H", timedelta(hours=2)),
        ("every 10 minutes", timedelta(minutes=10)),
        ("1 day", timedelta(days=1)),
    ],
)
def test_parse_interval_accepts_compact_and_phrase_forms(raw, expected) -> None:
    assert parse_interval(raw) == expected


@pytest.mark.parametrize("raw", ["", "0m", "soon", "1 week"])
def test_parse_interval_rejects_invalid_values(raw) -> None:
    with pytest.raises(IntervalParseError):
        parse_interval(raw)
