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

# View / filter options (Dutch values; full i18n is a follow-up phase)
VIEW_OPTIONS = ["Vandaag", "Morgen", "Week", "2 Weken", "Maand"]
LAYOUT_OPTIONS = ["Lijst", "Agenda"]
ALLES = "Alles"

# Meal planning (Phase 1: calendar-backed display)
MEALS_ENTITY = "sensor.familyboard_meals"
MEAL_DEFAULT_HOUR = 18
MEAL_LOOKAHEAD_DAYS = 7
MEAL_PLACEHOLDER = "Nog niet gepland"
