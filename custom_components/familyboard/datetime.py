"""FamilyBoard datetime entities (replaces input_datetime helpers)."""

from __future__ import annotations

import logging
from datetime import datetime

from homeassistant.components.datetime import DateTimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, get_device_info

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up FamilyBoard datetime entities from a config entry."""
    now = dt_util.now().replace(minute=0, second=0, microsecond=0)
    end = now.replace(hour=now.hour + 1) if now.hour < 23 else now

    entities = [
        FamilyBoardDateTime(
            unique_id="familyboard_event_start",
            translation_key="event_start",
            icon="mdi:clock-start",
            initial=now,
        ),
        FamilyBoardDateTime(
            unique_id="familyboard_event_end",
            translation_key="event_end",
            icon="mdi:clock-end",
            initial=end,
        ),
        FamilyBoardDateTime(
            unique_id="familyboard_day_start",
            translation_key="day_start",
            icon="mdi:calendar-start",
            initial=now,
        ),
        FamilyBoardDateTime(
            unique_id="familyboard_day_end",
            translation_key="day_end",
            icon="mdi:calendar-end",
            initial=end,
        ),
    ]
    async_add_entities(entities, True)
    fb = hass.data.setdefault(DOMAIN, {})
    fb["datetime"] = {
        "event_start": entities[0],
        "event_end": entities[1],
        "day_start": entities[2],
        "day_end": entities[3],
    }


class FamilyBoardDateTime(DateTimeEntity, RestoreEntity):
    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, unique_id: str, translation_key: str, icon: str, initial: datetime) -> None:
        self._attr_unique_id = unique_id
        self._attr_translation_key = translation_key
        self._attr_icon = icon
        self._attr_native_value = initial
        self._attr_device_info = get_device_info()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last and last.state not in (None, "unknown", "unavailable"):
            try:
                self._attr_native_value = datetime.fromisoformat(last.state)
            except (ValueError, TypeError):
                pass

    async def async_set_value(self, value: datetime) -> None:
        if value.tzinfo is None:
            value = value.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
        self._attr_native_value = value
        self.async_write_ha_state()
