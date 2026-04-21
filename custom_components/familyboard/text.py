"""FamilyBoard text entities (replaces input_text helpers)."""

from __future__ import annotations

import logging

from homeassistant.components.text import TextEntity
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
    """Set up FamilyBoard text entities from a config entry."""
    title = FamilyBoardText(
        unique_id="familyboard_event_title",
        translation_key="event_title",
        icon="mdi:format-title",
        max_value=255,
    )
    countdown_label = FamilyBoardText(
        unique_id="familyboard_countdown_label",
        translation_key="countdown_label",
        icon="mdi:rocket-launch",
        max_value=80,
    )
    async_add_entities([title, countdown_label], True)
    fb = hass.data.setdefault(DOMAIN, {})
    fb["text"] = {
        "event_title": title,
        "countdown_label": countdown_label,
    }


class FamilyBoardText(TextEntity, RestoreEntity):
    """Text entity replacing an `input_text` helper."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_mode = "text"

    def __init__(
        self, unique_id: str, translation_key: str, icon: str, max_value: int
    ) -> None:
        """Initialize the text entity with metadata and an empty value."""
        self._attr_unique_id = unique_id
        self._attr_suggested_object_id = unique_id
        self._attr_translation_key = translation_key
        self._attr_icon = icon
        self._attr_native_max = max_value
        self._attr_native_value = ""
        self._attr_device_info = get_device_info()

    async def async_added_to_hass(self) -> None:
        """Restore the previous value on startup."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last and last.state not in (None, "unknown", "unavailable"):
            self._attr_native_value = last.state

    async def async_set_value(self, value: str) -> None:
        """Update the stored value."""
        self._attr_native_value = value or ""
        self.async_write_ha_state()
