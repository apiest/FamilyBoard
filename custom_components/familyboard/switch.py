"""FamilyBoard switch entities (replaces input_boolean helpers)."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, get_device_info

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up FamilyBoard switch entities from a config entry."""
    all_day = FamilyBoardSwitch(
        unique_id="familyboard_event_all_day",
        translation_key="event_all_day",
        icon="mdi:weather-sunny",
    )
    show_reminders = FamilyBoardSwitch(
        unique_id="familyboard_show_reminders",
        translation_key="show_reminders",
        icon="mdi:bell",
        default_on=True,
    )
    async_add_entities([all_day, show_reminders], True)
    fb = hass.data.setdefault(DOMAIN, {})
    fb["switch"] = {"event_all_day": all_day, "show_reminders": show_reminders}


class FamilyBoardSwitch(SwitchEntity, RestoreEntity):
    """Switch entity replacing an `input_boolean` helper."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(
        self,
        unique_id: str,
        translation_key: str,
        icon: str,
        default_on: bool = False,
    ) -> None:
        """Initialize the switch with metadata and default state."""
        self._attr_unique_id = unique_id
        self._attr_translation_key = translation_key
        self._attr_icon = icon
        self._attr_is_on = default_on
        self._default_on = default_on
        self._attr_device_info = get_device_info()

    async def async_added_to_hass(self) -> None:
        """Restore the previous on/off state on startup."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last and last.state in ("on", "off"):
            self._attr_is_on = last.state == "on"
        else:
            self._attr_is_on = self._default_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        self._attr_is_on = False
        self.async_write_ha_state()
