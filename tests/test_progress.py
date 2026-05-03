"""Tests for the per-member daily progress logic in the coordinator.

Focus: shared chores must credit *every* member listed on the chore
(not just one), so checking off a shared chore (e.g. "take out the
trash") moves the progress ring for everyone responsible.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
import pytest

from custom_components.familyboard import FamilyBoardCoordinator


def _make_conf(shared_members: list[str]) -> dict[str, Any]:
    """Build a minimal coordinator conf with one shared chore."""
    return {
        "members": [
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
        "shared_chores": [
            {
                "entity": "todo.shared_trash",
                "members": shared_members,
                "name": "Trash",
            }
        ],
    }


@pytest.fixture
def stub_coordinator(hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch):
    """Build a coordinator with calendar/todo I/O stubbed out.

    Returns a `(coordinator, set_todo_items)` pair. `set_todo_items`
    replaces the response for `_fetch_todo_items(entity)` on every
    subsequent tick.
    """

    def _factory(shared_members: list[str]):
        coordinator = FamilyBoardCoordinator(hass, _make_conf(shared_members))
        # Avoid touching real meal-suggestion storage.
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


async def test_shared_chore_credits_every_listed_member(
    hass: HomeAssistant, stub_coordinator
) -> None:
    """Checking off a shared chore must increment progress for all listed members."""
    coordinator, set_todos = stub_coordinator(["Alice", "Bob"])

    # Tick 1: shared chore is active for both members.
    set_todos("todo.shared_trash", [{"uid": "trash-1", "summary": "Trash"}])
    result1 = await coordinator._async_update_data()
    assert result1["progress"]["Alice"]["completed"] == 0
    assert result1["progress"]["Bob"]["completed"] == 0
    assert result1["progress"]["Alice"]["total"] == 1
    assert result1["progress"]["Bob"]["total"] == 1

    # Tick 2: chore is checked off — list comes back empty.
    set_todos("todo.shared_trash", [])
    result2 = await coordinator._async_update_data()

    assert result2["progress"]["Alice"]["completed"] == 1
    assert result2["progress"]["Bob"]["completed"] == 1
    assert result2["progress"]["Alice"]["total"] == 1
    assert result2["progress"]["Bob"]["total"] == 1


async def test_shared_chore_credits_only_listed_members(
    hass: HomeAssistant, stub_coordinator
) -> None:
    """A shared chore listing only Alice must not affect Bob's progress."""
    coordinator, set_todos = stub_coordinator(["Alice"])

    set_todos("todo.shared_trash", [{"uid": "x", "summary": "Solo"}])
    await coordinator._async_update_data()

    set_todos("todo.shared_trash", [])
    result = await coordinator._async_update_data()

    assert result["progress"]["Alice"]["completed"] == 1
    assert result["progress"]["Bob"]["completed"] == 0
    assert result["progress"]["Bob"]["total"] == 0
