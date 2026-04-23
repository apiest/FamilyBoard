"""Sensors for FamilyBoard.

- `sensor.familyboard_chores`     — combined chore list with datetime + uid
- `sensor.familyboard_compliment` — time-of-day greeting
- `sensor.familyboard_meals`      — today's meal + upcoming week
- `sensor.familyboard_recent_meals` — scored recent meal titles for the picker
- `sensor.familyboard_members`    — member metadata for cards
- `sensor.familyboard_progress`   — per-member chore progress
"""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    MEAL_LOOKAHEAD_DAYS,
    MEAL_PLACEHOLDER,
    get_device_info,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up FamilyBoard sensor entities from a config entry."""
    conf = hass.data[DOMAIN]["config"]
    coordinator = hass.data[DOMAIN]["coordinator"]

    async_add_entities(
        [
            FamilyBoardChoresSensor(coordinator, conf),
            FamilyBoardComplimentSensor(),
            FamilyBoardMealsSensor(coordinator, conf),
            FamilyBoardRecentMealsSensor(coordinator, conf),
            FamilyBoardMembersSensor(coordinator),
            FamilyBoardProgressSensor(coordinator),
        ],
        True,
    )


class FamilyBoardChoresSensor(CoordinatorEntity, SensorEntity):
    """Sensor that provides a combined chore list for all members."""

    _attr_has_entity_name = True
    _attr_translation_key = "chores"

    def __init__(self, coordinator: DataUpdateCoordinator, conf: dict) -> None:
        """Store the coordinator and resolved config."""
        super().__init__(coordinator)
        self._conf = conf
        self._attr_unique_id = "familyboard_chores"
        self._attr_suggested_object_id = "familyboard_chores"
        self._attr_icon = "mdi:bell-ring"
        self._attr_device_info = get_device_info()

    @property
    def native_value(self) -> int:
        """Return the number of chore items currently aggregated."""
        return len(self._get_items())

    @property
    def extra_state_attributes(self) -> dict:
        """Expose the full chore list as an attribute for cards."""
        return {"items": self._get_items()}

    def _get_items(self) -> list[dict]:
        """Return the sorted aggregated chore list from the coordinator."""
        if not self.coordinator.data:
            return []
        return self.coordinator.data.get("all_chores_sorted", [])


class FamilyBoardComplimentSensor(SensorEntity):
    """Sensor that provides time-of-day motivational messages."""

    _attr_has_entity_name = True
    _attr_translation_key = "compliment"

    def __init__(self) -> None:
        """Initialize the compliment sensor."""
        self._attr_unique_id = "familyboard_compliment_integrated"
        self._attr_suggested_object_id = "familyboard_compliment"
        self._attr_icon = "mdi:hand-wave"
        self._attr_device_info = get_device_info()

    @property
    def native_value(self) -> str:
        """Return a Dutch greeting based on the current hour."""
        hour = dt_util.now().hour
        if hour < 6:
            return "Slaap lekker! \U0001f319"
        if hour < 12:
            return "Goedemorgen! \u2600\ufe0f"
        if hour < 18:
            return "Goed bezig vandaag! \U0001f4aa"
        return "Fijne avond! \U0001f319"

    @property
    def should_poll(self) -> bool:
        """Poll periodically so the greeting updates as the day progresses."""
        return True


class FamilyBoardMembersSensor(CoordinatorEntity, SensorEntity):
    """Sensor exposing member metadata for the filter card."""

    _attr_has_entity_name = True
    _attr_translation_key = "members"

    def __init__(self, coordinator: DataUpdateCoordinator) -> None:
        """Store the coordinator reference."""
        super().__init__(coordinator)
        self._attr_unique_id = "familyboard_members"
        self._attr_suggested_object_id = "familyboard_members"
        self._attr_icon = "mdi:account-group"
        self._attr_device_info = get_device_info()

    @property
    def native_value(self) -> int:
        """Return the number of configured members."""
        if not self.coordinator.data:
            return 0
        return len(self.coordinator.data.get("members_meta", []))

    @property
    def extra_state_attributes(self) -> dict:
        """Expose member metadata + shared calendars/chores for cards."""
        if not self.coordinator.data:
            return {"members": [], "shared_calendars": [], "shared_chores": []}
        return {
            "members": self.coordinator.data.get("members_meta", []),
            "shared_calendars": self.coordinator.data.get("shared_calendars", []),
            "shared_chores": self.coordinator.data.get("shared_chores", []),
        }


class FamilyBoardProgressSensor(CoordinatorEntity, SensorEntity):
    """Sensor exposing per-member chore progress for the progress card."""

    _attr_has_entity_name = True
    _attr_translation_key = "progress"

    def __init__(self, coordinator: DataUpdateCoordinator) -> None:
        """Store the coordinator reference."""
        super().__init__(coordinator)
        self._attr_unique_id = "familyboard_progress"
        self._attr_suggested_object_id = "familyboard_progress"
        self._attr_icon = "mdi:progress-check"
        self._attr_device_info = get_device_info()

    @property
    def native_value(self) -> int:
        """Return the total number of completed chores across members."""
        if not self.coordinator.data:
            return 0
        progress = self.coordinator.data.get("progress", {})
        return sum(p.get("completed", 0) for p in progress.values())

    @property
    def extra_state_attributes(self) -> dict:
        """Expose per-member completion percentages for the progress card."""
        if not self.coordinator.data:
            return {"members": []}
        progress = self.coordinator.data.get("progress", {})
        members_meta = self.coordinator.data.get("members_meta", [])
        members = []
        for meta in members_meta:
            name = meta["name"]
            p = progress.get(name, {"total": 0, "completed": 0})
            total = p["total"]
            completed = p["completed"]
            percentage = round((completed / total) * 100) if total > 0 else 0
            members.append(
                {
                    "name": name,
                    "color": meta.get("color", "#4A90D9"),
                    "picture": meta.get("picture"),
                    "person": meta.get("person"),
                    "total": total,
                    "completed": completed,
                    "percentage": percentage,
                }
            )
        return {"members": members}


class FamilyBoardMealsSensor(CoordinatorEntity, SensorEntity):
    """Sensor exposing tonight's meal + the upcoming week of meals.

    State is the title of today's meal (or ``MEAL_PLACEHOLDER`` when
    nothing is planned). Attributes expose ``tonight`` (today's meal
    dict or ``None``), ``week`` (list of one entry per upcoming day,
    each with ``date``, ``weekday`` and ``meal``), and
    ``meal_calendar_entity`` so cards can call ``calendar.create_event``
    against the right target.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "meals"

    def __init__(self, coordinator: DataUpdateCoordinator, conf: dict) -> None:
        """Store the coordinator and resolved config."""
        super().__init__(coordinator)
        self._conf = conf
        self._attr_unique_id = "familyboard_meals"
        self._attr_suggested_object_id = "familyboard_meals"
        self._attr_icon = "mdi:silverware-fork-knife"
        self._attr_device_info = get_device_info()

    def _meals(self) -> list[dict]:
        """Return the upcoming meals list from the coordinator."""
        if not self.coordinator.data:
            return []
        return self.coordinator.data.get("meals", [])

    def _tonight(self) -> dict | None:
        """Return today's first meal entry, if any."""
        today_iso = dt_util.now().date().isoformat()
        for meal in self._meals():
            if meal.get("date") == today_iso:
                return meal
        return None

    @property
    def native_value(self) -> str:
        """Return tonight's meal title or the empty placeholder."""
        tonight = self._tonight()
        if tonight and tonight.get("title"):
            return tonight["title"]
        return MEAL_PLACEHOLDER

    @property
    def extra_state_attributes(self) -> dict:
        """Expose tonight + the upcoming week as a flat list for cards."""
        meals_by_date: dict[str, dict] = {}
        for meal in self._meals():
            meals_by_date.setdefault(meal["date"], meal)

        today = dt_util.now().date()
        week: list[dict] = []
        for offset in range(MEAL_LOOKAHEAD_DAYS):
            day = today + timedelta(days=offset)
            iso = day.isoformat()
            week.append(
                {
                    "date": iso,
                    "weekday": day.strftime("%A"),
                    "meal": meals_by_date.get(iso),
                }
            )
        return {
            "tonight": self._tonight(),
            "week": week,
            "meal_calendar_entity": self._conf.get("meal_calendar"),
        }


class FamilyBoardRecentMealsSensor(CoordinatorEntity, SensorEntity):
    """Sensor exposing recently used meal titles for the quick picker.

    State is the number of distinct titles. Attributes expose ``items``
    (the scored, deduped list capped at ``MEAL_PICKER_LIMIT``) and
    ``meal_calendar_entity`` so cards can call ``calendar.create_event``
    against the right target.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "recent_meals"

    def __init__(self, coordinator: DataUpdateCoordinator, conf: dict) -> None:
        """Store the coordinator and resolved config."""
        super().__init__(coordinator)
        self._conf = conf
        self._attr_unique_id = "familyboard_recent_meals"
        self._attr_suggested_object_id = "familyboard_recent_meals"
        self._attr_icon = "mdi:history"
        self._attr_device_info = get_device_info()

    def _items(self) -> list[dict]:
        """Return the scored recent meals list from the coordinator."""
        if not self.coordinator.data:
            return []
        return self.coordinator.data.get("recent_meals", [])

    @property
    def native_value(self) -> int:
        """Return the number of distinct recent meal titles."""
        return len(self._items())

    @property
    def extra_state_attributes(self) -> dict:
        """Expose the scored items + the meal calendar entity."""
        return {
            "items": self._items(),
            "meal_calendar_entity": self._conf.get("meal_calendar"),
        }
