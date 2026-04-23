"""Tests for the recent-meals scoring helper and binary sensor."""

from __future__ import annotations

from datetime import date as _date, timedelta
from unittest.mock import MagicMock

from homeassistant.util import dt as dt_util

from custom_components.familyboard.binary_sensor import (
    FamilyBoardMealsUnplannedBinarySensor,
)
from custom_components.familyboard.const import MEAL_LOOKAHEAD_DAYS
from custom_components.familyboard.helpers import (
    is_meal_placeholder,
    meal_penalty,
    score_recent_meals,
)


def test_is_meal_placeholder_recognises_skips() -> None:
    """Placeholder titles are detected case-insensitively."""
    assert is_meal_placeholder("")
    assert is_meal_placeholder("-")
    assert is_meal_placeholder("Geen")
    assert is_meal_placeholder("none")
    assert not is_meal_placeholder("Pasta")


def test_meal_penalty_anchors_and_interpolation() -> None:
    """Penalty matches anchors and interpolates linearly between them."""
    assert meal_penalty(0) == 10.0
    assert meal_penalty(3) == 6.0
    assert meal_penalty(7) == 3.0
    assert meal_penalty(14) == 1.0
    assert meal_penalty(30) == 0.0
    # Interpolation: midway between (7, 3.0) and (14, 1.0) at d=10.5 → 2.0.
    assert abs(meal_penalty(10) - (3.0 + (1.0 - 3.0) * (10 - 7) / (14 - 7))) < 1e-9


def test_score_recent_meals_skips_placeholders_and_dedups() -> None:
    """Dedup case-insensitive; placeholders excluded; sorted by score."""
    today = _date(2026, 4, 20)
    events = [
        {"title": "Pasta", "date": "2026-04-19"},
        {"title": "pasta", "date": "2026-04-15"},
        {"title": "Pasta", "date": "2026-03-10"},
        {"title": "Stamppot", "date": "2026-04-05"},
        {"title": "Stamppot", "date": "2026-03-20"},
        {"title": "Stamppot", "date": "2026-03-01"},
        {"title": "geen", "date": "2026-04-18"},
        {"title": "-", "date": "2026-04-17"},
    ]
    items = score_recent_meals(events, today)
    titles = [i["title"] for i in items]
    # Only Pasta + Stamppot remain (placeholders skipped).
    assert set(titles) == {"Pasta", "Stamppot"}
    # Stamppot: 3 uses, last 15d ago → score 3 - ~0.71 ≈ 2.29.
    # Pasta:    3 uses, last 1d ago  → score 3 - ~7.33 ≈ -4.33.
    # Stamppot should outrank Pasta thanks to recency penalty.
    assert items[0]["title"] == "Stamppot"


def _make_binary_sensor(meals: list[dict]) -> FamilyBoardMealsUnplannedBinarySensor:
    """Build the unplanned-meals binary sensor with a stubbed coordinator."""
    coordinator = MagicMock()
    coordinator.data = {"meals": meals}
    coordinator.last_update_success = True
    return FamilyBoardMealsUnplannedBinarySensor(coordinator)


def test_meals_unplanned_on_when_window_has_gaps() -> None:
    """Empty meals → on, all upcoming dates listed."""
    sensor = _make_binary_sensor([])
    assert sensor.is_on is True
    attrs = sensor.extra_state_attributes
    assert attrs["count"] == MEAL_LOOKAHEAD_DAYS
    assert attrs["next_unplanned"] == dt_util.now().date().isoformat()


def test_meals_unplanned_off_when_every_day_covered() -> None:
    """Every upcoming day has either a real or skipped event → off."""
    today = dt_util.now().date()
    meals = [
        {
            "date": (today + timedelta(days=offset)).isoformat(),
            "title": "Stamppot" if offset % 2 == 0 else "geen",
            "start": (today + timedelta(days=offset)).isoformat(),
            "end": (today + timedelta(days=offset)).isoformat(),
            "all_day": True,
            "status": "planned" if offset % 2 == 0 else "skipped",
        }
        for offset in range(MEAL_LOOKAHEAD_DAYS)
    ]
    sensor = _make_binary_sensor(meals)
    assert sensor.is_on is False
    assert sensor.extra_state_attributes["count"] == 0


def test_meals_unplanned_skipped_counts_as_planned() -> None:
    """Even a skipped placeholder removes the day from the gap list."""
    today = dt_util.now().date()
    meals = [
        {
            "date": today.isoformat(),
            "title": "geen",
            "start": today.isoformat(),
            "end": today.isoformat(),
            "all_day": True,
            "status": "skipped",
        }
    ]
    sensor = _make_binary_sensor(meals)
    attrs = sensor.extra_state_attributes
    # Today is covered (skipped); only days 1..6 are unplanned.
    assert today.isoformat() not in attrs["unplanned_dates"]
    assert attrs["count"] == MEAL_LOOKAHEAD_DAYS - 1
