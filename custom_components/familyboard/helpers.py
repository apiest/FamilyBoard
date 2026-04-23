"""Shared helpers used across FamilyBoard modules."""

from __future__ import annotations

from datetime import date as _date
from itertools import pairwise
from typing import Any

from .const import MEAL_EMPTY_TITLES, MEAL_PENALTY_ANCHORS, MEAL_PICKER_LIMIT


def is_meal_placeholder(title: str | None) -> bool:
    """Return True when the meal title means 'deliberately no meal'."""
    if title is None:
        return True
    return title.strip().lower() in MEAL_EMPTY_TITLES


def meal_penalty(days_since: int) -> float:
    """Linear-interpolated penalty by days since last use; 30+ → 0."""
    anchors = MEAL_PENALTY_ANCHORS
    if days_since <= anchors[0][0]:
        return anchors[0][1]
    if days_since >= anchors[-1][0]:
        return anchors[-1][1]
    for (d0, p0), (d1, p1) in pairwise(anchors):
        if d0 <= days_since <= d1:
            if d1 == d0:
                return p0
            ratio = (days_since - d0) / (d1 - d0)
            return p0 + (p1 - p0) * ratio
    return 0.0


def score_recent_meals(
    events: list[dict[str, Any]],
    today: _date,
) -> list[dict[str, Any]]:
    """Return scored, deduped recent meal titles sorted by score desc.

    ``events`` items must have ``title`` and ``date`` (ISO yyyy-mm-dd).
    Placeholders are skipped. Result is capped at ``MEAL_PICKER_LIMIT``.
    """
    grouped: dict[str, dict[str, Any]] = {}
    for ev in events:
        title = (ev.get("title") or "").strip()
        if is_meal_placeholder(title):
            continue
        key = title.lower()
        try:
            ev_date = _date.fromisoformat(ev["date"])
        except (KeyError, ValueError):
            continue
        entry = grouped.get(key)
        if entry is None:
            grouped[key] = {
                "title": title,
                "uses": 1,
                "last_used": ev_date,
            }
        else:
            entry["uses"] += 1
            if ev_date > entry["last_used"]:
                entry["last_used"] = ev_date
                entry["title"] = title  # keep most-recent capitalisation

    items: list[dict[str, Any]] = []
    for entry in grouped.values():
        days_since = (today - entry["last_used"]).days
        score = entry["uses"] - meal_penalty(days_since)
        items.append(
            {
                "title": entry["title"],
                "uses": entry["uses"],
                "last_used": entry["last_used"].isoformat(),
                "days_since": days_since,
                "score": round(score, 2),
            }
        )

    items.sort(key=lambda i: (i["score"], -i["days_since"]), reverse=True)
    return items[:MEAL_PICKER_LIMIT]


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
