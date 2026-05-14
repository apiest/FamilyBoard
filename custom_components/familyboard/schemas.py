"""Voluptuous schemas for FamilyBoard YAML config and options flow."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.helpers import config_validation as cv
import voluptuous as vol

from .const import CALENDAR_CATEGORIES

_LOGGER = logging.getLogger(__name__)

EXTRA_CALENDAR_SCHEMA = vol.Schema(
    {
        vol.Required("entity"): cv.entity_id,
        vol.Required("label"): cv.string,
        vol.Optional("default_summary"): cv.string,
        vol.Optional("default_description"): cv.string,
        vol.Optional("category"): vol.In(CALENDAR_CATEGORIES),
    }
)

TRASH_SCHEMA = vol.Schema(
    {
        vol.Required("type"): cv.string,
        vol.Required("sensor"): cv.entity_id,
        vol.Optional("label"): cv.string,
        vol.Optional("color"): cv.string,
        vol.Optional("emoji"): cv.string,
        # Default False for new (UI-added) entries: adding a trash sensor
        # no longer silently auto-creates two chores. The YAML / v1
        # migration paths preserve the legacy True default — see
        # ``subentries.upsert_yaml`` / ``migrate_options_to_subentries``.
        vol.Optional("reminder_bins", default=False): cv.boolean,
        vol.Optional("reminder_kliko", default=False): cv.boolean,
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
        vol.Optional("category"): vol.In(CALENDAR_CATEGORIES),
    }
)

SHARED_CALENDAR_SCHEMA = vol.Schema(
    {
        vol.Required("entity"): cv.entity_id,
        vol.Required("members"): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional("name"): cv.string,
        vol.Optional("color"): cv.string,
        vol.Optional("category"): vol.In(CALENDAR_CATEGORIES),
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

# Phase 2.5: AI-assisted meal suggestion. ``ai_task_entity`` is the only
# required field. ``day_overrides`` keys are lowercase English weekday
# names (``monday``..``sunday``).
DAY_OVERRIDE_SCHEMA = vol.Schema(
    {
        vol.Optional("note"): cv.string,
        vol.Optional("max_minutes"): vol.All(int, vol.Range(min=1, max=240)),
    }
)

MEAL_PLANNER_SCHEMA = vol.Schema(
    {
        vol.Required("ai_task_entity"): cv.entity_id,
        vol.Optional("shopping_list"): cv.entity_id,
        vol.Optional("cuisines", default=[]): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional("pantry_staples", default=[]): vol.All(
            cv.ensure_list, [cv.string]
        ),
        vol.Optional("restrictions", default=[]): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional("max_minutes"): vol.All(int, vol.Range(min=1, max=240)),
        vol.Optional("day_overrides", default={}): vol.Schema(
            {cv.string: DAY_OVERRIDE_SCHEMA}
        ),
        vol.Optional("extra_notes", default=""): cv.string,
    }
)

# Public, single-block ``meals:`` shape (preferred). Carries both the
# calendar entity and the planner-prompt configuration. Mirrors
# ``MEAL_PLANNER_SCHEMA`` plus ``calendar``.
MEALS_SCHEMA = vol.Schema(
    {
        vol.Optional("calendar"): cv.entity_id,
        vol.Optional("ai_task_entity"): cv.entity_id,
        vol.Optional("shopping_list"): cv.entity_id,
        vol.Optional("cuisines", default=[]): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional("pantry_staples", default=[]): vol.All(
            cv.ensure_list, [cv.string]
        ),
        vol.Optional("restrictions", default=[]): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional("max_minutes"): vol.All(int, vol.Range(min=1, max=240)),
        vol.Optional("day_overrides", default={}): vol.Schema(
            {cv.string: DAY_OVERRIDE_SCHEMA}
        ),
        vol.Optional("extra_notes", default=""): cv.string,
    }
)


def _expand_meals_block(value: dict[str, Any]) -> dict[str, Any]:
    """Translate ``meals:`` into legacy ``meal_calendar`` + ``meal_planner``.

    The ``meals:`` block is the preferred public shape (single key,
    ``calendar`` nested inside). Internally we still consume
    ``meal_calendar`` + ``meal_planner``; this normalizer keeps that
    pipeline unchanged. The legacy keys remain accepted for
    backward-compat, with a deprecation warning if they're used.
    """
    if not isinstance(value, dict):
        return value
    out = dict(value)
    meals = out.pop("meals", None)
    if meals is not None:
        meals = dict(meals)
        cal = meals.pop("calendar", None)
        if cal:
            out.setdefault("meal_calendar", cal)
        if meals:
            out.setdefault("meal_planner", meals)
    elif "meal_planner" in out or "meal_calendar" in out:
        _LOGGER.warning(
            "FamilyBoard: 'meal_calendar' / 'meal_planner' YAML keys are "
            "deprecated. Replace them with a single 'meals:' block "
            "(calendar + planner fields nested inside). See README."
        )
    return out


DISPLAY_SCHEMA = vol.Schema(
    {
        vol.Optional("due_today_enabled", default=True): cv.boolean,
        vol.Optional("due_today_color", default="#3498DB"): cv.string,
        vol.Optional("due_soon_enabled", default=True): cv.boolean,
        vol.Optional("due_soon_color", default="#E67E22"): cv.string,
        vol.Optional("overdue_enabled", default=True): cv.boolean,
        vol.Optional("overdue_color", default="#E74C3C"): cv.string,
    }
)


OPTIONS_SCHEMA = vol.All(
    _expand_meals_block,
    vol.Schema(
        {
            vol.Required("members", default=[]): vol.All(
                cv.ensure_list, [MEMBER_SCHEMA]
            ),
            vol.Optional("trash", default=[]): vol.All(cv.ensure_list, [TRASH_SCHEMA]),
            vol.Optional("shared_calendars", default=[]): vol.All(
                cv.ensure_list, [SHARED_CALENDAR_SCHEMA]
            ),
            vol.Optional("shared_chores", default=[]): vol.All(
                cv.ensure_list, [SHARED_CHORE_SCHEMA]
            ),
            vol.Optional("meal_calendar"): cv.entity_id,
            vol.Optional("meal_planner"): MEAL_PLANNER_SCHEMA,
            vol.Optional("display"): DISPLAY_SCHEMA,
        }
    ),
)


def default_options() -> dict:
    """Return a fresh empty-but-valid options dict."""
    return {
        "members": [],
        "trash": [],
        "shared_calendars": [],
        "shared_chores": [],
    }
