"""Constants for the FamilyBoard integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

DOMAIN = "familyboard"
SCAN_INTERVAL_MINUTES = 5
TASK_IDENTIFIER = "tasks.google.com"

# Shared device for all FamilyBoard entities
DEVICE_IDENTIFIER = (DOMAIN, "familyboard_main")
DEVICE_NAME = "FamilyBoard"
DEVICE_MANUFACTURER = "FamilyBoard"
DEVICE_MODEL = "Family dashboard hub"


def get_device_info() -> DeviceInfo:
    """Return DeviceInfo so all FB entities group under one device."""
    return DeviceInfo(
        identifiers={DEVICE_IDENTIFIER},
        name=DEVICE_NAME,
        manufacturer=DEVICE_MANUFACTURER,
        model=DEVICE_MODEL,
        entry_type=DeviceEntryType.SERVICE,
    )


# Owned entity ids (HA derives these from unique_id; listed here for reuse)
FILTER_ENTITY = "select.familyboard_calendar"
VIEW_ENTITY = "select.familyboard_view"
LAYOUT_ENTITY = "select.familyboard_layout"
EVENT_MEMBER_ENTITY = "select.familyboard_event_member"
EVENT_CALENDAR_ENTITY = "select.familyboard_event_calendar"
EVENT_TITLE_ENTITY = "text.familyboard_event_title"
EVENT_ALL_DAY_ENTITY = "switch.familyboard_event_all_day"
EVENT_START_ENTITY = "datetime.familyboard_event_start"
EVENT_END_ENTITY = "datetime.familyboard_event_end"
DAY_START_ENTITY = "datetime.familyboard_day_start"
DAY_END_ENTITY = "datetime.familyboard_day_end"

# Event countdown (FR-12) — user-editable label + target date,
# rendered by the `familyboard-countdown-card` Lovelace card.
COUNTDOWN_LABEL_ENTITY = "text.familyboard_countdown_label"
COUNTDOWN_DATE_ENTITY = "datetime.familyboard_countdown_date"

# Snooze / reminder engine
STORAGE_KEY = "familyboard_reminders"
STORAGE_VERSION = 1

# Trash chore auto-creation
TRASH_CHORE_STORAGE_KEY = "familyboard_trash_chores"
TRASH_CHORE_STORAGE_VERSION = 1
ACTION_PREFIX = "FB_SNOOZE"
NOTIFICATION_TAG_PREFIX = "familyboard_snooze_"
SNOOZE_STEP_MIN = 15
SNOOZE_LARGE_STEP_MIN = 60
SNOOZE_MAX_MIN = 240

# View / filter options. Stable, language-neutral keys; user-visible labels
# come from translations (entity.select.<key>.state.<key>).
VIEW_OPTIONS = ["today", "tomorrow", "week", "two_weeks", "month"]
LAYOUT_OPTIONS = ["list", "agenda"]
ALLES = "Alles"
# Legacy Dutch state values from earlier releases — restored states are mapped
# into the new keys to avoid breaking existing installs.
LEGACY_VIEW_STATE_MAP: dict[str, str] = {
    "Vandaag": "today",
    "Morgen": "tomorrow",
    "Week": "week",
    "2 Weken": "two_weeks",
    "Maand": "month",
}
LEGACY_LAYOUT_STATE_MAP: dict[str, str] = {
    "Lijst": "list",
    "Agenda": "agenda",
}

# Meal planning (Phase 1: calendar-backed display)
MEALS_ENTITY = "sensor.familyboard_meals"
MEALS_UNPLANNED_ENTITY = "binary_sensor.familyboard_meals_unplanned"
RECENT_MEALS_ENTITY = "sensor.familyboard_recent_meals"
MEAL_DEFAULT_HOUR = 18
MEAL_LOOKAHEAD_DAYS = 7
MEAL_PLACEHOLDER = "Nog niet gepland"
# Titles that mean "deliberately no meal" — count as planned, render 🚫.
MEAL_EMPTY_TITLES = frozenset({"", "-", "--", "?", "geen", "none", "n/a"})

# Phase 2: recent meals memory + scoring
MEAL_RECENT_WINDOW_DAYS = 90
MEAL_PICKER_LIMIT = 12
# Penalty anchors: days_since_last_use → penalty subtracted from use count.
# Linear interpolation between anchors; 30+ days → 0.
MEAL_PENALTY_ANCHORS: tuple[tuple[int, float], ...] = (
    (0, 10.0),
    (3, 6.0),
    (7, 3.0),
    (14, 1.0),
    (30, 0.0),
)
