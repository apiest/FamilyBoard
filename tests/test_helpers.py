"""Tests for custom_components.familyboard.helpers."""

from __future__ import annotations

from custom_components.familyboard.helpers import (
    member_calendar_entities,
    member_calendar_labels,
    primary_label,
)


def test_primary_label_default() -> None:
    member = {"name": "Berry"}
    assert primary_label(member) == "Berry priv\u00e9"


def test_primary_label_override() -> None:
    member = {"name": "Berry", "calendar_label": "Persoonlijk"}
    assert primary_label(member) == "Persoonlijk"


def test_member_calendar_labels(sample_member) -> None:
    assert member_calendar_labels(sample_member) == ["Berry priv\u00e9", "Werk"]


def test_member_calendar_labels_no_extras() -> None:
    member = {"name": "Berry", "calendar": "calendar.berry"}
    assert member_calendar_labels(member) == ["Berry priv\u00e9"]


def test_member_calendar_entities(sample_member) -> None:
    assert member_calendar_entities(sample_member) == [
        ("Berry priv\u00e9", "calendar.berry"),
        ("Werk", "calendar.berry_werk"),
    ]
