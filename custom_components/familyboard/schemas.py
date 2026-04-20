"""Voluptuous schemas for FamilyBoard YAML config and options flow."""

from __future__ import annotations

from homeassistant.helpers import config_validation as cv
import voluptuous as vol

EXTRA_CALENDAR_SCHEMA = vol.Schema(
    {
        vol.Required("entity"): cv.entity_id,
        vol.Required("label"): cv.string,
        vol.Optional("default_summary"): cv.string,
        vol.Optional("default_description"): cv.string,
    }
)

TRASH_SCHEMA = vol.Schema(
    {
        vol.Required("type"): cv.string,
        vol.Required("sensor"): cv.entity_id,
        vol.Optional("label"): cv.string,
        vol.Optional("color"): cv.string,
        vol.Optional("emoji"): cv.string,
    }
)

MEMBER_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Required("calendar"): cv.entity_id,
        vol.Optional("calendar_label"): cv.string,
        vol.Optional("calendar_default_summary"): cv.string,
        vol.Optional("calendar_default_description"): cv.string,
        vol.Optional("extra_calendars", default=[]): vol.All(
            cv.ensure_list, [EXTRA_CALENDAR_SCHEMA]
        ),
        vol.Optional("chores", default=[]): vol.All(cv.ensure_list, [cv.entity_id]),
        vol.Optional("person"): cv.entity_id,
        vol.Optional("color", default="#4A90D9"): cv.string,
        vol.Optional("notify"): cv.string,
    }
)

SHARED_CALENDAR_SCHEMA = vol.Schema(
    {
        vol.Required("entity"): cv.entity_id,
        vol.Required("members"): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional("name"): cv.string,
        vol.Optional("color"): cv.string,
    }
)

SHARED_CHORE_SCHEMA = vol.Schema(
    {
        vol.Required("entity"): cv.entity_id,
        vol.Required("members"): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional("type"): cv.string,
        vol.Optional("name"): cv.string,
        vol.Optional("color"): cv.string,
    }
)

OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Required("members", default=[]): vol.All(cv.ensure_list, [MEMBER_SCHEMA]),
        vol.Optional("trash", default=[]): vol.All(cv.ensure_list, [TRASH_SCHEMA]),
        vol.Optional("shared_calendars", default=[]): vol.All(
            cv.ensure_list, [SHARED_CALENDAR_SCHEMA]
        ),
        vol.Optional("shared_chores", default=[]): vol.All(
            cv.ensure_list, [SHARED_CHORE_SCHEMA]
        ),
        vol.Optional("meal_calendar"): cv.entity_id,
    }
)


def default_options() -> dict:
    """Return a fresh empty-but-valid options dict."""
    return {
        "members": [],
        "trash": [],
        "shared_calendars": [],
        "shared_chores": [],
    }
