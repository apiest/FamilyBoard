"""Tests for FamilyBoardMealsSensor."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

from homeassistant.util import dt as dt_util

from custom_components.familyboard.const import MEAL_LOOKAHEAD_DAYS, MEAL_PLACEHOLDER
from custom_components.familyboard.sensor import FamilyBoardMealsSensor


def _make_sensor(
    meals: list[dict], meal_calendar: str | None
) -> FamilyBoardMealsSensor:
    """Build a meals sensor with a stubbed coordinator."""
    coordinator = MagicMock()
    coordinator.data = {"meals": meals}
    coordinator.last_update_success = True
    return FamilyBoardMealsSensor(coordinator, {"meal_calendar": meal_calendar})


def test_meals_sensor_empty_returns_placeholder() -> None:
    """No meals + no calendar configured → placeholder state, empty week."""
    sensor = _make_sensor([], None)
    assert sensor.native_value == MEAL_PLACEHOLDER
    attrs = sensor.extra_state_attributes
    assert attrs["tonight"] is None
    assert attrs["meal_calendar_entity"] is None
    assert len(attrs["week"]) == MEAL_LOOKAHEAD_DAYS
    assert all(day["meal"] is None for day in attrs["week"])


def test_meals_sensor_today_meal_surfaces() -> None:
    """Meal scheduled for today → state matches title and tonight populated."""
    today = dt_util.now().date().isoformat()
    meals = [
        {
            "date": today,
            "title": "Pasta bolognese",
            "start": f"{today}T18:00:00",
            "end": f"{today}T19:00:00",
            "description": "",
            "uid": "meal-1",
            "all_day": False,
        }
    ]
    sensor = _make_sensor(meals, "calendar.meals")
    assert sensor.native_value == "Pasta bolognese"
    attrs = sensor.extra_state_attributes
    assert attrs["tonight"]["title"] == "Pasta bolognese"
    assert attrs["meal_calendar_entity"] == "calendar.meals"
    assert attrs["week"][0]["meal"]["title"] == "Pasta bolognese"


def test_meals_sensor_future_meal_no_tonight() -> None:
    """Future-only meal → state placeholder, week entry populated on right day."""
    tomorrow = (dt_util.now().date() + timedelta(days=2)).isoformat()
    meals = [
        {
            "date": tomorrow,
            "title": "Stamppot",
            "start": f"{tomorrow}T18:00:00",
            "end": f"{tomorrow}T19:00:00",
            "description": "",
            "uid": "meal-2",
            "all_day": False,
        }
    ]
    sensor = _make_sensor(meals, "calendar.meals")
    assert sensor.native_value == MEAL_PLACEHOLDER
    attrs = sensor.extra_state_attributes
    assert attrs["tonight"] is None
    matching = [day for day in attrs["week"] if day["date"] == tomorrow]
    assert matching and matching[0]["meal"]["title"] == "Stamppot"
