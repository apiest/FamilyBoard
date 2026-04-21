"""Binary sensors for FamilyBoard.

- `binary_sensor.familyboard_meals_unplanned` — on when one or more of
  the upcoming ``MEAL_LOOKAHEAD_DAYS`` has no meal event at all.
  Placeholder events (`MEAL_EMPTY_TITLES`, e.g. "geen") count as
  planned, so deliberately-skipped days do not trigger the alert.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
from homeassistant.util import dt as dt_util

from .const import DOMAIN, MEAL_LOOKAHEAD_DAYS, get_device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up FamilyBoard binary sensor entities from a config entry."""
    coordinator = hass.data[DOMAIN]["coordinator"]
    async_add_entities([FamilyBoardMealsUnplannedBinarySensor(coordinator)], True)


class FamilyBoardMealsUnplannedBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor that flags upcoming days with no meal planned."""

    _attr_has_entity_name = True
    _attr_translation_key = "meals_unplanned"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: DataUpdateCoordinator) -> None:
        """Store the coordinator reference."""
        super().__init__(coordinator)
        self._attr_unique_id = "familyboard_meals_unplanned"
        self._attr_suggested_object_id = "familyboard_meals_unplanned"
        self._attr_icon = "mdi:silverware-variant"
        self._attr_device_info = get_device_info()

    def _meals_by_date(self) -> dict[str, list[dict]]:
        """Group upcoming meals by ISO date."""
        out: dict[str, list[dict]] = {}
        if not self.coordinator.data:
            return out
        for meal in self.coordinator.data.get("meals", []):
            out.setdefault(meal["date"], []).append(meal)
        return out

    def _unplanned_dates(self) -> list[str]:
        """Return ISO dates in the lookahead window with no meal at all."""
        meals_by_date = self._meals_by_date()
        today = dt_util.now().date()
        dates: list[str] = []
        for offset in range(MEAL_LOOKAHEAD_DAYS):
            iso = (today + timedelta(days=offset)).isoformat()
            if not meals_by_date.get(iso):
                dates.append(iso)
        return dates

    @property
    def is_on(self) -> bool:
        """Return True when any upcoming day lacks a meal entry."""
        return bool(self._unplanned_dates())

    @property
    def extra_state_attributes(self) -> dict:
        """Expose the unplanned dates for automations and cards."""
        dates = self._unplanned_dates()
        return {
            "unplanned_dates": dates,
            "count": len(dates),
            "next_unplanned": dates[0] if dates else None,
        }
