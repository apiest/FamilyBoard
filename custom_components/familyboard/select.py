"""FamilyBoard select entities (replaces input_select helpers).

Provides 5 select entities owned by the integration:

- `select.familyboard_calendar`         — filter chip (Alles + members)
- `select.familyboard_view`             — week planner view
- `select.familyboard_layout`           — list/agenda layout toggle
- `select.familyboard_event_member`     — Add Event: who
- `select.familyboard_event_calendar`   — Add Event: which calendar
"""

from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    ALLES,
    DOMAIN,
    LAYOUT_OPTIONS,
    LEGACY_LAYOUT_STATE_MAP,
    LEGACY_VIEW_STATE_MAP,
    VIEW_OPTIONS,
    get_device_info,
)
from .helpers import member_calendar_labels

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up FamilyBoard select entities from a config entry."""
    conf = hass.data[DOMAIN]["config"]
    members = conf["members"]
    member_names = [m["name"] for m in members]

    calendar_filter = FamilyBoardSelect(
        unique_id="familyboard_calendar",
        translation_key="calendar_filter",
        icon="mdi:filter-variant",
        options=[ALLES, *member_names],
        default=ALLES,
        object_id="familyboard_calendar",
    )
    view = FamilyBoardSelect(
        unique_id="familyboard_view",
        translation_key="view",
        icon="mdi:eye",
        options=VIEW_OPTIONS,
        default="week",
        object_id="familyboard_view",
        legacy_state_map=LEGACY_VIEW_STATE_MAP,
    )
    layout = FamilyBoardSelect(
        unique_id="familyboard_layout",
        translation_key="layout",
        icon="mdi:view-dashboard-variant",
        options=LAYOUT_OPTIONS,
        default="list",
        object_id="familyboard_layout",
        legacy_state_map=LEGACY_LAYOUT_STATE_MAP,
    )
    event_member = FamilyBoardSelect(
        unique_id="familyboard_event_member",
        translation_key="event_member",
        icon="mdi:account",
        options=member_names,
        default=member_names[0] if member_names else None,
        object_id="familyboard_event_member",
    )
    event_calendar = FamilyBoardEventCalendarSelect(
        members=members,
        member_select=event_member,
    )

    async_add_entities(
        [calendar_filter, view, layout, event_member, event_calendar], True
    )

    fb = hass.data.setdefault(DOMAIN, {})
    fb["select"] = {
        "calendar": calendar_filter,
        "view": view,
        "layout": layout,
        "event_member": event_member,
        "event_calendar": event_calendar,
    }


class FamilyBoardSelect(SelectEntity, RestoreEntity):
    """A simple persistent select entity."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(
        self,
        unique_id: str,
        translation_key: str,
        icon: str,
        options: list[str],
        default: str | None,
        object_id: str | None = None,
        legacy_state_map: dict[str, str] | None = None,
    ) -> None:
        """Initialize the select with metadata, options and default value."""
        self._attr_unique_id = unique_id
        self._attr_translation_key = translation_key
        self._attr_icon = icon
        self._attr_options = list(options)
        self._attr_current_option = (
            default if default in options else (options[0] if options else None)
        )
        self._legacy_state_map = legacy_state_map or {}
        self._attr_device_info = get_device_info()
        # Pin the entity_id so it matches the constants the dashboard uses,
        # regardless of what the translation key would otherwise produce.
        if object_id:
            self._attr_suggested_object_id = object_id
            self.entity_id = f"select.{object_id}"

    async def async_added_to_hass(self) -> None:
        """Restore the previously selected option on startup."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if not last:
            return
        state = last.state
        if state in (self._attr_options or []):
            self._attr_current_option = state
        elif state in self._legacy_state_map:
            mapped = self._legacy_state_map[state]
            if mapped in (self._attr_options or []):
                _LOGGER.info(
                    "Migrating legacy %s state %r -> %r",
                    self.entity_id,
                    state,
                    mapped,
                )
                self._attr_current_option = mapped

    async def async_select_option(self, option: str) -> None:
        """Select a new option, ignoring values not in the option list."""
        if option not in (self._attr_options or []):
            _LOGGER.warning(
                "Ignoring select_option(%s) for %s; not in %s",
                option,
                self.entity_id,
                self._attr_options,
            )
            return
        self._attr_current_option = option
        self.async_write_ha_state()

    def update_options(self, options: list[str], reset_to: str | None = None) -> None:
        """Replace options list. Optionally reset selection."""
        self._attr_options = list(options)
        if reset_to is not None and reset_to in options:
            self._attr_current_option = reset_to
        elif self._attr_current_option not in options:
            self._attr_current_option = options[0] if options else None
        self.async_write_ha_state()


class FamilyBoardEventCalendarSelect(FamilyBoardSelect):
    """Cascading select that updates options when event_member changes."""

    def __init__(
        self,
        members: list[dict],
        member_select: FamilyBoardSelect,
    ) -> None:
        """Initialize and seed options from the first member's calendars."""
        self._members_by_name = {m["name"]: m for m in members}
        self._member_select = member_select

        first_member = members[0] if members else None
        initial_options = member_calendar_labels(first_member) if first_member else [""]
        super().__init__(
            unique_id="familyboard_event_calendar",
            translation_key="event_calendar",
            icon="mdi:calendar",
            options=initial_options,
            default=initial_options[0],
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to member-select changes after registration."""
        await super().async_added_to_hass()
        if self._member_select.entity_id:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    [self._member_select.entity_id],
                    self._on_member_change,
                )
            )

    @callback
    def _on_member_change(self, event: Event) -> None:
        """Replace options when the selected member changes."""
        new_state = event.data.get("new_state")
        if not new_state:
            return
        member = self._members_by_name.get(new_state.state)
        if not member:
            return
        labels = member_calendar_labels(member)
        if list(self._attr_options or []) == list(labels):
            return
        self.update_options(labels, reset_to=labels[0] if labels else None)
