"""Tests for the subentry layer (migration, YAML upsert, compose_conf)."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.familyboard.const import (
    DOMAIN,
    SUBENTRY_EXTRA_CALENDAR,
    SUBENTRY_MEAL_DAY_OVERRIDE,
    SUBENTRY_MEAL_PLANNER,
    SUBENTRY_MEMBER,
    SUBENTRY_SHARED_CALENDAR,
    SUBENTRY_SHARED_CHORE,
    SUBENTRY_TRASH,
)
from custom_components.familyboard.subentries import (
    compose_conf,
    extra_calendar_uid,
    meal_day_override_uid,
    meal_planner_uid,
    member_uid,
    migrate_options_to_subentries,
    supported_subentry_types,
    trash_uid,
    upsert_yaml,
)


def _legacy_options() -> dict[str, Any]:
    """Return a representative v1 options dict (covers every list type)."""
    return {
        "members": [
            {
                "name": "Alice",
                "calendar": "calendar.alice",
                "color": "#A8C8EC",
                "extra_calendars": [
                    {"entity": "calendar.alice_werk", "label": "Werk"},
                ],
                "chores": ["todo.alice"],
            },
            {
                "name": "Bob",
                "calendar": "calendar.bob",
                "color": "#B5E0C2",
                "extra_calendars": [],
                "chores": [],
            },
        ],
        "trash": [
            {"type": "rest", "sensor": "sensor.trash_rest"},
        ],
        "shared_calendars": [
            {
                "entity": "calendar.shared",
                "members": ["Alice", "Bob"],
                "name": "Shared",
            }
        ],
        "shared_chores": [
            {
                "entity": "todo.trash",
                "members": ["Alice", "Bob"],
                "type": "trash",
            }
        ],
        "meal_calendar": "calendar.meals",
        "meal_planner": {
            "ai_task_entity": "ai_task.test",
            "max_minutes": 30,
            "day_overrides": {"thursday": {"max_minutes": 15}},
        },
    }


def _make_entry(hass: HomeAssistant, version: int = 1) -> ConfigEntry:
    """Add a MockConfigEntry to ``hass`` with the given version."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        options=_legacy_options(),
        version=version,
        title="FamilyBoard",
    )
    entry.add_to_hass(hass)
    return entry


async def test_migrate_creates_one_subentry_per_item(
    hass: HomeAssistant,
) -> None:
    """Every legacy list item should become a subentry with a stable uid."""
    entry = _make_entry(hass, version=1)

    created = await migrate_options_to_subentries(hass, entry, dict(entry.options))
    # 2 members + 1 extra cal + 1 trash + 1 shared cal + 1 shared chore
    # + 1 meal planner + 1 meal day override = 8
    assert created == 8

    by_type: dict[str, list[ConfigSubentry]] = {}
    for sub in entry.subentries.values():
        by_type.setdefault(sub.subentry_type, []).append(sub)

    assert len(by_type[SUBENTRY_MEMBER]) == 2
    assert len(by_type[SUBENTRY_EXTRA_CALENDAR]) == 1
    assert len(by_type[SUBENTRY_TRASH]) == 1
    assert len(by_type[SUBENTRY_SHARED_CALENDAR]) == 1
    assert len(by_type[SUBENTRY_SHARED_CHORE]) == 1
    assert len(by_type[SUBENTRY_MEAL_PLANNER]) == 1
    assert len(by_type[SUBENTRY_MEAL_DAY_OVERRIDE]) == 1

    assert {s.unique_id for s in by_type[SUBENTRY_MEMBER]} == {
        member_uid("Alice"),
        member_uid("Bob"),
    }
    extra = by_type[SUBENTRY_EXTRA_CALENDAR][0]
    assert extra.unique_id == extra_calendar_uid("Alice", "calendar.alice_werk")
    assert extra.data["parent_member"] == "Alice"

    trash = by_type[SUBENTRY_TRASH][0]
    assert trash.unique_id == trash_uid("rest")
    # Migration carve-out: legacy trash defaults to True for both reminders.
    assert trash.data["reminder_bins"] is True
    assert trash.data["reminder_kliko"] is True

    planner = by_type[SUBENTRY_MEAL_PLANNER][0]
    assert planner.unique_id == meal_planner_uid()
    assert planner.data["meal_calendar"] == "calendar.meals"
    # day_overrides stripped from planner data — they live in their own subentry.
    assert "day_overrides" not in planner.data

    override = by_type[SUBENTRY_MEAL_DAY_OVERRIDE][0]
    assert override.unique_id == meal_day_override_uid("thursday")
    assert override.data["weekday"] == "thursday"
    assert override.data["max_minutes"] == 15


async def test_migrate_is_idempotent(hass: HomeAssistant) -> None:
    """Running migration twice must not duplicate subentries."""
    entry = _make_entry(hass, version=1)
    first = await migrate_options_to_subentries(hass, entry, dict(entry.options))
    second = await migrate_options_to_subentries(hass, entry, dict(entry.options))
    assert first == 8
    assert second == 0


async def test_compose_conf_round_trips(hass: HomeAssistant) -> None:
    """compose_conf(entry) should reproduce the legacy conf shape."""
    entry = _make_entry(hass, version=1)
    await migrate_options_to_subentries(hass, entry, dict(entry.options))

    conf = compose_conf(entry)

    member_names = {m["name"] for m in conf["members"]}
    assert member_names == {"Alice", "Bob"}
    alice = next(m for m in conf["members"] if m["name"] == "Alice")
    assert alice["chores"] == ["todo.alice"]
    assert len(alice["extra_calendars"]) == 1
    assert alice["extra_calendars"][0]["entity"] == "calendar.alice_werk"

    assert conf["trash"][0]["sensor"] == "sensor.trash_rest"
    assert conf["shared_calendars"][0]["entity"] == "calendar.shared"
    assert conf["shared_chores"][0]["entity"] == "todo.trash"

    assert conf["meal_calendar"] == "calendar.meals"
    assert conf["meal_planner"]["ai_task_entity"] == "ai_task.test"
    assert conf["meal_planner"]["day_overrides"]["thursday"]["max_minutes"] == 15


async def test_upsert_yaml_updates_in_place(hass: HomeAssistant) -> None:
    """Re-importing modified YAML must update existing subentries by uid."""
    entry = _make_entry(hass, version=1)
    await migrate_options_to_subentries(hass, entry, dict(entry.options))

    yaml = _legacy_options()
    yaml["members"][0]["color"] = "#FF00FF"  # change Alice's color
    await upsert_yaml(hass, entry, yaml)

    alice_sub = next(
        s
        for s in entry.subentries.values()
        if s.subentry_type == SUBENTRY_MEMBER and s.unique_id == member_uid("Alice")
    )
    assert alice_sub.data["color"] == "#FF00FF"

    # Subentry count unchanged.
    by_type: dict[str, int] = {}
    for sub in entry.subentries.values():
        by_type[sub.subentry_type] = by_type.get(sub.subentry_type, 0) + 1
    assert by_type[SUBENTRY_MEMBER] == 2


async def test_upsert_yaml_preserves_ui_only_subentries(
    hass: HomeAssistant,
) -> None:
    """A subentry added via the UI without a YAML twin is left intact."""
    entry = _make_entry(hass, version=1)
    await migrate_options_to_subentries(hass, entry, dict(entry.options))

    # Simulate a UI-added member named "Carol".
    hass.config_entries.async_add_subentry(
        entry,
        ConfigSubentry(
            subentry_type=SUBENTRY_MEMBER,
            title="Carol",
            unique_id=member_uid("Carol"),
            data={"name": "Carol", "calendar": "calendar.carol"},
        ),
    )

    # Re-import the original YAML (no Carol mentioned).
    await upsert_yaml(hass, entry, _legacy_options())

    member_uids = {
        s.unique_id
        for s in entry.subentries.values()
        if s.subentry_type == SUBENTRY_MEMBER
    }
    assert member_uid("Carol") in member_uids
    assert member_uid("Alice") in member_uids
    assert member_uid("Bob") in member_uids


async def test_supported_subentry_types_filters_singletons(
    hass: HomeAssistant,
) -> None:
    """All known types are returned so reconfigure cogwheels keep working.

    Singleton / saturation guards live inside the relevant flow's
    ``async_step_user`` (it aborts on duplicate), not at the picker
    level. extra_calendar is still hidden when no member exists.
    """
    entry = _make_entry(hass, version=1)
    await migrate_options_to_subentries(hass, entry, dict(entry.options))

    types = supported_subentry_types(entry)
    # meal_planner stays in the dict so the existing row keeps its
    # reconfigure cogwheel — duplicate-add is blocked inside the flow.
    assert SUBENTRY_MEAL_PLANNER in types
    assert types[SUBENTRY_MEAL_PLANNER]["supports_reconfigure"] is True
    # extra_calendar offered because Alice + Bob are members.
    assert SUBENTRY_EXTRA_CALENDAR in types
    # Day-overrides always offered; saturation handled inside the flow.
    assert SUBENTRY_MEAL_DAY_OVERRIDE in types

    # Add the remaining six weekdays — type still listed (cogwheel) but
    # the flow's ``_show`` aborts on add.
    for wd in ("monday", "tuesday", "wednesday", "friday", "saturday", "sunday"):
        hass.config_entries.async_add_subentry(
            entry,
            ConfigSubentry(
                subentry_type=SUBENTRY_MEAL_DAY_OVERRIDE,
                title=wd,
                unique_id=meal_day_override_uid(wd),
                data={"weekday": wd},
            ),
        )
    types = supported_subentry_types(entry)
    assert SUBENTRY_MEAL_DAY_OVERRIDE in types


async def test_yaml_setup_upserts_subentries(hass: HomeAssistant) -> None:
    """Loading the integration with a YAML config creates subentries (no v1 entry)."""
    yaml = _legacy_options()
    assert await async_setup_component(hass, DOMAIN, {DOMAIN: yaml})
    await hass.async_block_till_done()

    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1
    entry = entries[0]

    # Subentries created from the YAML-only setup.
    member_uids = {
        s.unique_id
        for s in entry.subentries.values()
        if s.subentry_type == SUBENTRY_MEMBER
    }
    assert member_uids == {member_uid("Alice"), member_uid("Bob")}

    # compose_conf still produces a usable conf dict.
    conf = compose_conf(entry)
    assert {m["name"] for m in conf["members"]} == {"Alice", "Bob"}
