"""FamilyBoard switch entities (replaces input_boolean helpers)."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    CALENDAR_CATEGORIES,
    DEFAULT_CALENDAR_CATEGORY,
    DEFAULT_SHARED_CALENDAR_CATEGORY,
    DOMAIN,
    get_device_info,
)

_LOGGER = logging.getLogger(__name__)


def _active_categories(conf: dict) -> list[str]:
    """Return the distinct calendar categories used in ``conf``.

    Order follows ``CALENDAR_CATEGORIES`` so the resulting switch list is
    stable across restarts regardless of YAML ordering.
    """
    used: set[str] = set()
    for member in conf.get("members", []):
        primary = member.get("category", DEFAULT_CALENDAR_CATEGORY)
        used.add(primary)
        for extra in member.get("extra_calendars", []):
            used.add(extra.get("category", primary))
    for shared in conf.get("shared_calendars", []):
        used.add(shared.get("category", DEFAULT_SHARED_CALENDAR_CATEGORY))
    return [c for c in CALENDAR_CATEGORIES if c in used]


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

    conf = hass.data[DOMAIN]["config"]
    active = _active_categories(conf)

    # Purge category switches whose category is no longer in use, so the
    # filter chips don't keep showing stale toggles after a YAML edit or
    # after a category was removed from CALENDAR_CATEGORIES entirely.
    ent_reg = er.async_get(hass)
    active_unique_ids = {f"familyboard_category_{k}" for k in active}
    for entry_ in list(ent_reg.entities.values()):
        if (
            entry_.platform == DOMAIN
            and entry_.domain == "switch"
            and entry_.unique_id.startswith("familyboard_category_")
            and entry_.unique_id not in active_unique_ids
        ):
            ent_reg.async_remove(entry_.entity_id)

    category_switches: dict[str, FamilyBoardSwitch] = {}
    for key in active:
        category_switches[key] = FamilyBoardSwitch(
            unique_id=f"familyboard_category_{key}",
            translation_key=f"category_{key}",
            icon="mdi:calendar-filter",
            default_on=True,
            object_id=f"familyboard_category_{key}",
        )

    async_add_entities([all_day, show_reminders, *category_switches.values()], True)
    fb = hass.data.setdefault(DOMAIN, {})
    fb["switch"] = {
        "event_all_day": all_day,
        "show_reminders": show_reminders,
        "categories": category_switches,
    }


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
        object_id: str | None = None,
    ) -> None:
        """Initialize the switch with metadata and default state."""
        self._attr_unique_id = unique_id
        self._attr_translation_key = translation_key
        self._attr_icon = icon
        self._attr_is_on = default_on
        self._default_on = default_on
        self._attr_device_info = get_device_info()
        if object_id:
            self._attr_suggested_object_id = object_id
            self.entity_id = f"switch.{object_id}"

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
