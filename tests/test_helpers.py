"""Tests for custom_components.familyboard.helpers."""

from __future__ import annotations

from custom_components.familyboard.helpers import (
    member_calendar_entities,
    member_calendar_labels,
    primary_label,
)


def test_primary_label_default() -> None:
    member = {"name": "Alice"}
    assert primary_label(member) == "Alice priv\u00e9"


def test_primary_label_override() -> None:
    member = {"name": "Alice", "calendar_label": "Persoonlijk"}
    assert primary_label(member) == "Persoonlijk"


def test_member_calendar_labels(sample_member) -> None:
    assert member_calendar_labels(sample_member) == ["Alice priv\u00e9", "Werk"]


def test_member_calendar_labels_no_extras() -> None:
    member = {"name": "Alice", "calendar": "calendar.alice"}
    assert member_calendar_labels(member) == ["Alice priv\u00e9"]


def test_member_calendar_entities(sample_member) -> None:
    assert member_calendar_entities(sample_member) == [
        ("Alice priv\u00e9", "calendar.alice"),
        ("Werk", "calendar.alice_werk"),
    ]
