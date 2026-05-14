"""Tests for chore-filter visibility & dedup (Phase 1 fixes).

Covers:
- Shared chores bypass the view-window trim and always reach the
  Algemene (`all_chores_sorted`) list.
- Shared chores without a UID are deduped across multiple members.
- Unknown member name in `shared_chores.members` triggers exactly
  one WARNING per ``(entity, name)`` pair.
- Personal+shared `todo.*` entity overlap triggers a WARNING at
  coordinator init.
- Every ``const.VIEW_OPTIONS`` key is handled by the backend
  ``_get_view_window`` (parametric guard so adding a new view key
  forces a matching backend branch).
"""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
import pytest

from custom_components.familyboard import FamilyBoardCoordinator
from custom_components.familyboard.const import VIEW_ENTITY, VIEW_OPTIONS


def _base_conf(
    *,
    members: list[dict] | None = None,
    shared_chores: list[dict] | None = None,
) -> dict[str, Any]:
    """Build a minimal coordinator config with optional overrides."""
    return {
        "members": members
        if members is not None
        else [
            {
                "name": "Alice",
                "calendar": "calendar.alice",
                "color": "#A8C8EC",
                "extra_calendars": [],
                "chores": [],
            },
            {
                "name": "Bob",
                "calendar": "calendar.bob",
                "color": "#B5E0C2",
                "extra_calendars": [],
                "chores": [],
            },
        ],
        "trash": [],
        "shared_calendars": [],
        "shared_chores": shared_chores or [],
    }


@pytest.fixture
def coordinator_factory(hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch):
    """Build a coordinator with calendar/todo I/O stubbed out."""

    def _factory(conf: dict[str, Any]):
        coordinator = FamilyBoardCoordinator(hass, conf)
        coordinator._meal_suggestion = None

        todos: dict[str, list[dict]] = {}

        async def fake_fetch_events(*_args, **_kwargs):
            return []

        async def fake_fetch_todo_items(entity_id: str, status: str = "needs_action"):
            return list(todos.get(entity_id, []))

        async def fake_fetch_meals(*_args, **_kwargs):
            return []

        async def fake_fetch_recent_meals(*_args, **_kwargs):
            return []

        monkeypatch.setattr(coordinator, "_fetch_events", fake_fetch_events)
        monkeypatch.setattr(coordinator, "_fetch_todo_items", fake_fetch_todo_items)
        monkeypatch.setattr(coordinator, "_fetch_meals", fake_fetch_meals)
        monkeypatch.setattr(coordinator, "_fetch_recent_meals", fake_fetch_recent_meals)

        def set_todos(entity_id: str, items: list[dict]) -> None:
            todos[entity_id] = items

        return coordinator, set_todos

    return _factory


async def test_shared_chore_bypasses_view_window_trim(
    hass: HomeAssistant, coordinator_factory
) -> None:
    """A shared chore due in the future must still appear with view=today."""
    hass.states.async_set(VIEW_ENTITY, "today")
    conf = _base_conf(
        shared_chores=[
            {
                "entity": "todo.shared_trash",
                "members": ["Alice", "Bob"],
                "name": "Trash",
            }
        ]
    )
    coordinator, set_todos = coordinator_factory(conf)

    future_due = (dt_util.now().date() + timedelta(days=5)).isoformat()
    set_todos(
        "todo.shared_trash",
        [{"uid": "trash-future", "summary": "Trash", "due": future_due}],
    )

    result = await coordinator._async_update_data()
    summaries = [c["summary"] for c in result["all_chores_sorted"]]
    assert "Trash" in summaries, (
        f"Shared chore due {future_due} should appear with view=today; "
        f"got {summaries!r}"
    )


async def test_personal_chore_respects_view_window_trim(
    hass: HomeAssistant, coordinator_factory
) -> None:
    """Personal chores in the future must still be trimmed by the view."""
    hass.states.async_set(VIEW_ENTITY, "today")
    members = [
        {
            "name": "Alice",
            "calendar": "calendar.alice",
            "color": "#A8C8EC",
            "extra_calendars": [],
            "chores": ["todo.alice"],
        }
    ]
    coordinator, set_todos = coordinator_factory(_base_conf(members=members))

    future_due = (dt_util.now().date() + timedelta(days=5)).isoformat()
    set_todos(
        "todo.alice",
        [{"uid": "personal-future", "summary": "FutureTask", "due": future_due}],
    )

    result = await coordinator._async_update_data()
    summaries = [c["summary"] for c in result["all_chores_sorted"]]
    assert "FutureTask" not in summaries, (
        "Personal chore beyond view=today window must be trimmed."
    )


async def test_personal_chore_with_caldav_datetime_due_visible(
    hass: HomeAssistant, coordinator_factory
) -> None:
    """CalDAV returns due as full ISO datetime; chore must still appear."""
    hass.states.async_set(VIEW_ENTITY, "today")
    members = [
        {
            "name": "Alice",
            "calendar": "calendar.alice",
            "color": "#A8C8EC",
            "extra_calendars": [],
            "chores": ["todo.alice"],
        }
    ]
    coordinator, set_todos = coordinator_factory(_base_conf(members=members))

    today_iso = dt_util.now().date().isoformat()
    # CalDAV/Nextcloud style: "YYYY-MM-DDTHH:MM:SS+TZ"
    caldav_due = f"{today_iso}T07:00:00+02:00"
    set_todos(
        "todo.alice",
        [{"uid": "caldav-today", "summary": "Tas Inpakken", "due": caldav_due}],
    )

    result = await coordinator._async_update_data()
    summaries = [c["summary"] for c in result["all_chores_sorted"]]
    assert "Tas Inpakken" in summaries, (
        f"Chore with CalDAV datetime due {caldav_due!r} should appear "
        f"with view=today; got {summaries!r}"
    )


async def test_shared_chore_without_uid_dedups_across_members(
    hass: HomeAssistant, coordinator_factory
) -> None:
    """Two members, no UID — the algemene list should still show one row."""
    conf = _base_conf(
        shared_chores=[
            {
                "entity": "todo.shared_trash",
                "members": ["Alice", "Bob"],
                "name": "Trash",
            }
        ]
    )
    coordinator, set_todos = coordinator_factory(conf)
    set_todos("todo.shared_trash", [{"summary": "Trash", "due": None}])

    result = await coordinator._async_update_data()
    trash_rows = [c for c in result["all_chores_sorted"] if c["summary"] == "Trash"]
    assert len(trash_rows) == 1, (
        f"Expected one deduped row for UID-less shared chore, got {len(trash_rows)}"
    )


async def test_unknown_shared_member_warns_once(
    hass: HomeAssistant,
    coordinator_factory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A typo'd member name should produce exactly one WARNING per (entity, name)."""
    conf = _base_conf(
        shared_chores=[
            {
                "entity": "todo.shared_trash",
                "members": ["Alice", "Charlie"],  # Charlie is not configured
                "name": "Trash",
            }
        ]
    )
    coordinator, set_todos = coordinator_factory(conf)
    set_todos("todo.shared_trash", [{"uid": "x", "summary": "Trash"}])

    with caplog.at_level(logging.WARNING, logger="custom_components.familyboard"):
        await coordinator._async_update_data()
        await coordinator._async_update_data()
        await coordinator._async_update_data()

    matches = [
        rec
        for rec in caplog.records
        if "Charlie" in rec.message and "todo.shared_trash" in rec.message
    ]
    assert len(matches) == 1, (
        f"Expected exactly one WARNING for the unknown shared member, got "
        f"{len(matches)}: {[r.message for r in matches]}"
    )


async def test_personal_shared_overlap_warns_at_init(
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An entity listed both personal and shared must log a WARNING."""
    conf = _base_conf(
        members=[
            {
                "name": "Alice",
                "calendar": "calendar.alice",
                "color": "#A8C8EC",
                "extra_calendars": [],
                "chores": ["todo.shared_trash"],  # ← also a shared entity
            },
            {
                "name": "Bob",
                "calendar": "calendar.bob",
                "color": "#B5E0C2",
                "extra_calendars": [],
                "chores": [],
            },
        ],
        shared_chores=[
            {
                "entity": "todo.shared_trash",
                "members": ["Alice", "Bob"],
                "name": "Trash",
            }
        ],
    )

    with caplog.at_level(logging.WARNING, logger="custom_components.familyboard"):
        FamilyBoardCoordinator(hass, conf)

    overlaps = [
        rec
        for rec in caplog.records
        if "todo.shared_trash" in rec.message
        and "personal" in rec.message.lower()
        and "shared" in rec.message.lower()
    ]
    assert len(overlaps) == 1, (
        f"Expected one overlap WARNING at coordinator init, got {len(overlaps)}: "
        f"{[r.message for r in overlaps]}"
    )


@pytest.mark.parametrize("view_key", VIEW_OPTIONS)
async def test_get_view_window_handles_every_view_option(
    hass: HomeAssistant, coordinator_factory, view_key: str
) -> None:
    """Every `VIEW_OPTIONS` key must produce a valid (start, end) window.

    Guard against drift: adding a new key in `const.py::VIEW_OPTIONS`
    without a matching branch in `_get_view_window` will fail this test.
    The frontend `_filterByView` (JS) must mirror the same key set —
    that invariant is documented in `.github/copilot-instructions.md`.
    """
    hass.states.async_set(VIEW_ENTITY, view_key)
    coordinator, _ = coordinator_factory(_base_conf())
    window = coordinator._get_view_window(dt_util.now())
    assert window is not None, (
        f"_get_view_window returned None for known VIEW_OPTIONS key {view_key!r}"
    )
    start, end = window
    assert start <= end, f"View {view_key!r} produced inverted window {window!r}"
