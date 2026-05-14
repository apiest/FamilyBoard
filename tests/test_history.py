"""Tests for the chore-completion history sensors (Phase 5).

The coordinator records each completed chore into:

- ``_completion_totals`` — per-member monotonic counter exposed via
  ``sensor.familyboard_completions_total_<member>`` with
  ``state_class=TOTAL_INCREASING`` so the recorder/statistics engine
  can derive hourly/daily/weekly aggregates (energy-dashboard
  pattern).
- ``_recent_completions`` — bounded log surfaced as
  ``sensor.familyboard_recent_chores`` attributes for the recent-list
  card.

Attribution honors the Phase 4 claim model: unclaimed shared chores
are logged with ``member=None`` and bump no counter.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
import pytest

from custom_components.familyboard import FamilyBoardCoordinator
from custom_components.familyboard.const import CHORE_HISTORY_MAX_ENTRIES


def _make_conf(shared_members: list[str]) -> dict[str, Any]:
    """Two-member household with one personal + one shared chore list."""
    return {
        "members": [
            {
                "name": "Alice",
                "calendar": "calendar.alice",
                "color": "#A8C8EC",
                "extra_calendars": [],
                "chores": ["todo.alice"],
            },
            {
                "name": "Bob",
                "calendar": "calendar.bob",
                "color": "#B5E0C2",
                "extra_calendars": [],
                "chores": ["todo.bob"],
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
    """Build a coordinator with calendar/todo I/O stubbed out."""

    def _factory(shared_members: list[str] | None = None):
        coordinator = FamilyBoardCoordinator(
            hass, _make_conf(shared_members or ["Alice", "Bob"])
        )
        coordinator._meal_suggestion = None

        todos: dict[str, list[dict]] = {}

        async def fake_fetch_events(*_a, **_k):
            return []

        async def fake_fetch_todo_items(entity_id: str, status: str = "needs_action"):
            return list(todos.get(entity_id, []))

        async def fake_fetch_meals(*_a, **_k):
            return []

        async def fake_fetch_recent_meals(*_a, **_k):
            return []

        async def noop_refresh() -> None:
            return None

        async def noop_save(_data: Any) -> None:
            return None

        monkeypatch.setattr(coordinator, "_fetch_events", fake_fetch_events)
        monkeypatch.setattr(coordinator, "_fetch_todo_items", fake_fetch_todo_items)
        monkeypatch.setattr(coordinator, "_fetch_meals", fake_fetch_meals)
        monkeypatch.setattr(coordinator, "_fetch_recent_meals", fake_fetch_recent_meals)
        monkeypatch.setattr(coordinator, "async_request_refresh", noop_refresh)
        # Avoid hitting real Store I/O.
        monkeypatch.setattr(coordinator._history_store, "async_save", noop_save)
        monkeypatch.setattr(coordinator._claim_store, "async_save", noop_save)

        def set_todos(entity_id: str, items: list[dict]) -> None:
            todos[entity_id] = items

        return coordinator, set_todos

    return _factory


async def test_personal_completion_credits_owner(
    hass: HomeAssistant, stub_coordinator
) -> None:
    """A personal chore disappearing bumps its owner's counter and logs once."""
    coordinator, set_todos = stub_coordinator()
    await coordinator.async_load_claims()
    await coordinator.async_load_history()

    set_todos("todo.alice", [{"uid": "p-1", "summary": "Dishes"}])
    await coordinator._async_update_data()

    set_todos("todo.alice", [])
    result = await coordinator._async_update_data()

    assert result["completion_totals"]["Alice"] == 1
    assert result["completion_totals"]["Bob"] == 0
    entries = result["recent_completions"]
    assert len(entries) == 1
    assert entries[0]["member"] == "Alice"
    assert entries[0]["summary"] == "Dishes"
    assert entries[0]["source"] == "personal"


async def test_claimed_shared_completion_credits_claimer(
    hass: HomeAssistant, stub_coordinator
) -> None:
    """Claimed shared chore credits only the claimer."""
    coordinator, set_todos = stub_coordinator()
    await coordinator.async_load_claims()
    await coordinator.async_load_history()

    set_todos("todo.shared_trash", [{"uid": "s-1", "summary": "Trash"}])
    await coordinator._async_update_data()
    await coordinator.async_set_claim("s-1", "Bob")
    await coordinator._async_update_data()

    set_todos("todo.shared_trash", [])
    result = await coordinator._async_update_data()

    assert result["completion_totals"]["Bob"] == 1
    assert result["completion_totals"]["Alice"] == 0
    assert result["recent_completions"][0]["member"] == "Bob"
    assert result["recent_completions"][0]["source"] == "shared"


async def test_unclaimed_shared_completion_logged_without_credit(
    hass: HomeAssistant, stub_coordinator
) -> None:
    """Unclaimed shared chore is logged with member=None and bumps nobody."""
    coordinator, set_todos = stub_coordinator()
    await coordinator.async_load_claims()
    await coordinator.async_load_history()

    set_todos("todo.shared_trash", [{"uid": "s-2", "summary": "Trash"}])
    await coordinator._async_update_data()

    set_todos("todo.shared_trash", [])
    result = await coordinator._async_update_data()

    assert result["completion_totals"]["Alice"] == 0
    assert result["completion_totals"]["Bob"] == 0
    entries = result["recent_completions"]
    assert len(entries) == 1
    assert entries[0]["member"] is None
    assert entries[0]["source"] == "shared"


async def test_counter_is_monotonic_across_ticks(
    hass: HomeAssistant, stub_coordinator
) -> None:
    """Two separate completions keep bumping; counter never resets."""
    coordinator, set_todos = stub_coordinator()
    await coordinator.async_load_claims()
    await coordinator.async_load_history()

    set_todos("todo.alice", [{"uid": "p-1", "summary": "A"}])
    await coordinator._async_update_data()
    set_todos("todo.alice", [])
    await coordinator._async_update_data()

    set_todos("todo.alice", [{"uid": "p-2", "summary": "B"}])
    await coordinator._async_update_data()
    set_todos("todo.alice", [])
    result = await coordinator._async_update_data()

    assert result["completion_totals"]["Alice"] == 2
    assert [e["summary"] for e in result["recent_completions"][:2]] == ["B", "A"]


async def test_recent_log_pruned_by_count(
    hass: HomeAssistant, stub_coordinator
) -> None:
    """Recording > MAX_ENTRIES drops the oldest entries."""
    coordinator, _ = stub_coordinator()
    await coordinator.async_load_claims()
    await coordinator.async_load_history()

    overflow = CHORE_HISTORY_MAX_ENTRIES + 25
    for i in range(overflow):
        await coordinator._record_completion(
            uid=f"u-{i}",
            member="Alice",
            summary=f"chore-{i}",
            todo_entity="todo.alice",
            source="personal",
        )

    assert len(coordinator._recent_completions) == CHORE_HISTORY_MAX_ENTRIES
    # Newest first — most recent record is the last one we pushed.
    assert coordinator._recent_completions[0]["summary"] == f"chore-{overflow - 1}"


async def test_recent_log_pruned_by_age(hass: HomeAssistant, stub_coordinator) -> None:
    """Entries older than the age cap are dropped on prune."""
    coordinator, _ = stub_coordinator()
    await coordinator.async_load_claims()
    await coordinator.async_load_history()

    old_ts = (dt_util.now() - timedelta(days=120)).isoformat()
    coordinator._recent_completions = [
        {
            "ts": old_ts,
            "member": "Alice",
            "summary": "ancient",
            "uid": "old",
            "source": "personal",
            "todo_entity": "todo.alice",
        }
    ]
    await coordinator._record_completion(
        uid="fresh",
        member="Alice",
        summary="fresh",
        todo_entity="todo.alice",
        source="personal",
    )

    summaries = [e["summary"] for e in coordinator._recent_completions]
    assert "ancient" not in summaries
    assert "fresh" in summaries


async def test_history_persists_across_reload(
    hass: HomeAssistant, stub_coordinator, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Counters and recent log survive a coordinator restart via Store."""
    coordinator, set_todos = stub_coordinator()
    await coordinator.async_load_claims()
    await coordinator.async_load_history()

    set_todos("todo.alice", [{"uid": "p-1", "summary": "Dishes"}])
    await coordinator._async_update_data()
    set_todos("todo.alice", [])
    await coordinator._async_update_data()

    snapshot = {
        "completion_totals": dict(coordinator._completion_totals),
        "recent": list(coordinator._recent_completions),
    }

    # Fresh coordinator pretending the on-disk snapshot is the prior tick.
    new_coordinator = FamilyBoardCoordinator(hass, _make_conf(["Alice", "Bob"]))
    new_coordinator._meal_suggestion = None

    async def fake_load(*_a, **_k):
        return snapshot

    monkeypatch.setattr(new_coordinator._history_store, "async_load", fake_load)

    await new_coordinator.async_load_history()

    assert new_coordinator._completion_totals["Alice"] == 1
    assert new_coordinator._recent_completions[0]["summary"] == "Dishes"
