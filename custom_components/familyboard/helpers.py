"""Shared helpers used across FamilyBoard modules."""

from __future__ import annotations

from typing import Any


def primary_label(member: dict[str, Any]) -> str:
    """Return the label used for a member's primary calendar."""
    return member.get("calendar_label") or f"{member['name']} priv\u00e9"


def member_calendar_labels(member: dict[str, Any]) -> list[str]:
    """Return ordered list of all calendar labels for a member."""
    labels = [primary_label(member)]
    for extra in member.get("extra_calendars", []):
        labels.append(extra["label"])
    return labels


def member_calendar_entities(member: dict[str, Any]) -> list[tuple[str, str]]:
    """Return [(label, entity_id), ...] for primary + extras."""
    out = [(primary_label(member), member["calendar"])]
    for extra in member.get("extra_calendars", []):
        out.append((extra["label"], extra["entity"]))
    return out
