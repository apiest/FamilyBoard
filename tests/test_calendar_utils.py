"""Tests for the pure utility functions in custom_components.familyboard.calendar."""

from __future__ import annotations

from datetime import datetime

import pytest

from custom_components.familyboard.calendar import (
    MARKER_PREFIX,
    MARKER_SUFFIX,
    _build_marker,
    _event_key,
    _is_task,
    _parse_datetime_or_date,
)


def test_build_marker_format() -> None:
    marker = _build_marker(["Alice", "Bob"], ["#4A90D9", "#27AE60"])
    assert marker.startswith(MARKER_PREFIX)
    assert marker.endswith(MARKER_SUFFIX)
    assert "members=Alice,Bob" in marker
    assert "colors=#4A90D9,#27AE60" in marker


def test_is_task_detects_google_tasks_marker() -> None:
    assert _is_task({"description": "Sync from tasks.google.com"}) is True
    assert _is_task({"description": "regular note"}) is False
    assert _is_task({}) is False


def test_event_key_normalizes_summary() -> None:
    a = {"summary": "  Dentist  ", "start": "2026-01-01", "end": "2026-01-01"}
    b = {"summary": "DENTIST", "start": "2026-01-01", "end": "2026-01-01"}
    assert _event_key(a) == _event_key(b)


def test_parse_datetime_iso_with_tz() -> None:
    dt = _parse_datetime_or_date("2026-04-19T10:30:00+02:00")
    assert isinstance(dt, datetime)
    assert dt.tzinfo is not None


def test_parse_datetime_naive_gets_default_tz() -> None:
    dt = _parse_datetime_or_date("2026-04-19T10:30:00")
    assert dt.tzinfo is not None


def test_parse_date_only() -> None:
    dt = _parse_datetime_or_date("2026-04-19")
    assert dt.year == 2026 and dt.month == 4 and dt.day == 19
    assert dt.hour == 0 and dt.minute == 0


def test_parse_empty_raises() -> None:
    with pytest.raises(ValueError):
        _parse_datetime_or_date("")
