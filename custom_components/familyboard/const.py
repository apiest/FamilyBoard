"""Constants for the FamilyBoard integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

DOMAIN = "familyboard"
SCAN_INTERVAL_MINUTES = 5
TASK_IDENTIFIER = "tasks.google.com"

# Config-entry version. Bumped to 2 in v0.4.0 when list-shaped config
# (members, trash, shared_*, meal_planner.day_overrides) was migrated
# into HA subentries — see ``async_migrate_entry``.
CONFIG_ENTRY_VERSION = 2

# Subentry types managed via the integration page.
SUBENTRY_MEMBER = "member"
SUBENTRY_EXTRA_CALENDAR = "extra_calendar"
SUBENTRY_SHARED_CALENDAR = "shared_calendar"
SUBENTRY_SHARED_CHORE = "shared_chore"
SUBENTRY_TRASH = "trash"
SUBENTRY_MEAL_PLANNER = "meal_planner"
SUBENTRY_MEAL_DAY_OVERRIDE = "meal_day_override"
SUBENTRY_DISPLAY = "display"
SUBENTRY_CALDAV_CONNECTION = "caldav_connection"
SUBENTRY_TYPES: tuple[str, ...] = (
    SUBENTRY_MEMBER,
    SUBENTRY_EXTRA_CALENDAR,
    SUBENTRY_SHARED_CALENDAR,
    SUBENTRY_SHARED_CHORE,
    SUBENTRY_TRASH,
    SUBENTRY_MEAL_PLANNER,
    SUBENTRY_MEAL_DAY_OVERRIDE,
    SUBENTRY_DISPLAY,
    SUBENTRY_CALDAV_CONNECTION,
)
WEEKDAYS: tuple[str, ...] = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

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
VIEW_OPTIONS = [
    "today",
    "2_days",
    "3_days",
    "work_week",
    "week",
    "two_weeks",
    "month",
]
LAYOUT_OPTIONS = ["list", "agenda"]
ALLES = "Alles"

# Calendar category enum. Stable, language-neutral keys; user-visible
# labels live in translations (entity.select.calendar_category.state.<key>).
CALENDAR_CATEGORIES: tuple[str, ...] = (
    "personal",
    "work",
    "school",
    "hobby",
    "family",
    "other",
)
DEFAULT_CALENDAR_CATEGORY = "personal"
# Shared calendars are conceptually personal too — they default to the same
# category so toggling "Personal" off behaves consistently for events from
# either source. Users can still tag a shared calendar with an explicit
# `category:` in YAML to opt it into a different filter chip.
DEFAULT_SHARED_CALENDAR_CATEGORY = DEFAULT_CALENDAR_CATEGORY
CATEGORY_FILTER_ENTITY = "select.familyboard_calendar_category"
# Legacy Dutch state values from earlier releases — restored states are mapped
# into the new keys to avoid breaking existing installs.
LEGACY_VIEW_STATE_MAP: dict[str, str] = {
    "Vandaag": "today",
    "Morgen": "today",
    "Vandaag + Morgen": "2_days",
    "Week": "week",
    "2 Weken": "two_weeks",
    "Maand": "month",
    "tomorrow": "today",
    "today_tomorrow": "2_days",
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

# Phase 2.5: AI-assisted meal suggestion
MEAL_SUGGESTION_ENTITY = "sensor.familyboard_meal_suggestion"
MEAL_SUGGESTION_STORAGE_KEY = "familyboard_meal_suggestion"
MEAL_SUGGESTION_STORAGE_VERSION = 1
MEAL_SUGGESTION_PLACEHOLDER = "Geen suggestie"

# Phase 4: shared-chore claim store. `{uid: member_name}` map persisted
# across restarts. An unclaimed shared chore is visible to every listed
# member but credits nobody on completion; a claimed chore appears only
# on the claimer's card and credits them.
CHORE_CLAIM_STORAGE_KEY = "familyboard_chore_claims"
CHORE_CLAIM_STORAGE_VERSION = 1

# Phase 5: chore-completion history store. Per-member cumulative
# counters (energy-dashboard pattern) + a bounded recent-completions
# log for the recent-list card.
CHORE_HISTORY_STORAGE_KEY = "familyboard_chore_history"
CHORE_HISTORY_STORAGE_VERSION = 1
CHORE_HISTORY_MAX_ENTRIES = 500
CHORE_HISTORY_MAX_DAYS = 90
# Bucket thresholds used by the prompt builder when classifying recent meals.
MEAL_AVOID_DAYS = 14  # days_since < this → "recently eaten, do not suggest"
MEAL_FAVORITE_DAYS = 21  # days_since >= this → "forgotten favorite, inspire"
DEFAULT_MEAL_MAX_MINUTES = 30
DEFAULT_MEAL_CUISINES: tuple[str, ...] = (
    "Nederlands",
    "Italiaans",
    "Mexicaans",
    "Aziatisch",
    "Mediterraans",
    "Midden-Oosters",
)
DEFAULT_MEAL_PANTRY: tuple[str, ...] = (
    "zout",
    "peper",
    "olie",
    "boter",
    "ui",
    "knoflook",
    "kruiden",
    "melk",
    "eieren",
    "rijst",
    "pasta",
    "sojasaus",
    "ketjap",
    "tomatenblik",
    "bouillonblokjes",
)
DEFAULT_MEAL_RESTRICTIONS: tuple[str, ...] = ()
