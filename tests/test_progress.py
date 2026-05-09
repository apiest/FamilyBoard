"""Tests for the per-member daily progress logic in the coordinator.

Phase 4 (claim model) semantics:

- An *unclaimed* shared chore is visible to every listed member but
  credits **nobody** on completion.
- A shared chore *claimed* by member X appears only on X's card and
  credits **only** X on completion.
- Personal chores credit their owner (unchanged).
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

        async def noop_refresh() -> None:
            return None

        # Tests drive `_async_update_data` directly; suppress the
        # debouncer that `async_request_refresh` would otherwise leave
        # behind as a lingering timer.
        monkeypatch.setattr(coordinator, "async_request_refresh", noop_refresh)

        def set_todos(entity_id: str, items: list[dict]) -> None:
            todos[entity_id] = items

        return coordinator, set_todos

    return _factory


async def test_unclaimed_shared_chore_credits_nobody(
    hass: HomeAssistant, stub_coordinator
) -> None:
    """Completing an unclaimed shared chore must not bump any ring (Phase 4)."""
    coordinator, set_todos = stub_coordinator(["Alice", "Bob"])
    await coordinator.async_load_claims()  # ensure prune path is enabled

    # Tick 1: shared chore active, no claim.
    set_todos("todo.shared_trash", [{"uid": "trash-1", "summary": "Trash"}])
    result1 = await coordinator._async_update_data()
    assert result1["progress"]["Alice"]["completed"] == 0
    assert result1["progress"]["Bob"]["completed"] == 0
    # Visible to both because unclaimed:
    assert result1["progress"]["Alice"]["total"] == 0
    assert result1["progress"]["Bob"]["total"] == 0

    # Tick 2: completed.
    set_todos("todo.shared_trash", [])
    result2 = await coordinator._async_update_data()

    assert result2["progress"]["Alice"]["completed"] == 0, (
        "Unclaimed shared chore must not credit Alice"
    )
    assert result2["progress"]["Bob"]["completed"] == 0, (
        "Unclaimed shared chore must not credit Bob"
    )


async def test_claimed_shared_chore_credits_only_claimer(
    hass: HomeAssistant, stub_coordinator
) -> None:
    """A shared chore claimed by Alice credits only Alice on completion."""
    coordinator, set_todos = stub_coordinator(["Alice", "Bob"])
    await coordinator.async_load_claims()

    # Tick 1: shared chore active.
    set_todos("todo.shared_trash", [{"uid": "trash-1", "summary": "Trash"}])
    await coordinator._async_update_data()

    # Alice claims it.
    await coordinator.async_set_claim("trash-1", "Alice")

    # Tick 2 (after refresh triggered by claim): Alice sees it, Bob doesn't.
    result_claim = await coordinator._async_update_data()
    assert result_claim["progress"]["Alice"]["total"] == 1
    assert result_claim["progress"]["Bob"]["total"] == 0

    # Tick 3: completed.
    set_todos("todo.shared_trash", [])
    result_done = await coordinator._async_update_data()

    assert result_done["progress"]["Alice"]["completed"] == 1, (
        "Claimer should be credited on completion"
    )
    assert result_done["progress"]["Bob"]["completed"] == 0, (
        "Non-claimer must not be credited"
    )


async def test_release_claim_restores_unclaimed_visibility(
    hass: HomeAssistant, stub_coordinator
) -> None:
    """Releasing a claim brings the chore back onto every listed member's card."""
    coordinator, set_todos = stub_coordinator(["Alice", "Bob"])
    await coordinator.async_load_claims()

    set_todos("todo.shared_trash", [{"uid": "trash-1", "summary": "Trash"}])
    await coordinator.async_set_claim("trash-1", "Alice")
    result_claimed = await coordinator._async_update_data()
    assert result_claimed["progress"]["Bob"]["total"] == 0

    await coordinator.async_set_claim("trash-1", None)
    result_released = await coordinator._async_update_data()
    # Unclaimed → visible to both, credits nobody → totals 0
    assert result_released["progress"]["Alice"]["total"] == 0
    assert result_released["progress"]["Bob"]["total"] == 0
    # And the chore appears on the deduped algemene list
    assert any(c["summary"] == "Trash" for c in result_released["all_chores_sorted"])


async def test_claim_for_unknown_member_raises(
    hass: HomeAssistant, stub_coordinator
) -> None:
    """`async_set_claim` must reject an unknown member name."""
    from homeassistant.exceptions import HomeAssistantError

    coordinator, _ = stub_coordinator(["Alice", "Bob"])
    await coordinator.async_load_claims()
    with pytest.raises(HomeAssistantError):
        await coordinator.async_set_claim("trash-1", "Charlie")


async def test_orphan_claim_pruned_when_uid_disappears(
    hass: HomeAssistant, stub_coordinator
) -> None:
    """Stale claims for UIDs no longer present are dropped from the store."""
    coordinator, set_todos = stub_coordinator(["Alice", "Bob"])
    await coordinator.async_load_claims()

    set_todos("todo.shared_trash", [{"uid": "trash-1", "summary": "Trash"}])
    await coordinator.async_set_claim("trash-1", "Alice")
    await coordinator._async_update_data()
    assert "trash-1" in coordinator.claims

    # Chore vanishes (e.g. completed elsewhere).
    set_todos("todo.shared_trash", [])
    await coordinator._async_update_data()
    assert "trash-1" not in coordinator.claims, (
        "Claim for vanished UID should be pruned"
    )
