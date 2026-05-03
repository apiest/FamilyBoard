"""Tests for the meal-suggestion prompt builder."""

from __future__ import annotations

from datetime import date

from custom_components.familyboard.helpers import (
    _bucket_recent_meals,
    build_meal_prompt,
)


def _items() -> list[dict]:
    """Return a synthetic recent-meals attribute list."""
    return [
        {"title": "Spaghetti", "uses": 5, "days_since": 2, "score": 4.0},
        {"title": "Wraps", "uses": 3, "days_since": 12, "score": 2.0},
        {"title": "Stamppot", "uses": 6, "days_since": 25, "score": 6.0},
        {"title": "Risotto", "uses": 4, "days_since": 40, "score": 4.0},
    ]


def test_bucket_recent_meals_split() -> None:
    """Items <14d → recently_eaten asc; >=21d → forgotten_favorites."""
    recently, forgotten = _bucket_recent_meals(_items())
    assert [i["title"] for i in recently] == ["Spaghetti", "Wraps"]
    assert {i["title"] for i in forgotten} == {"Stamppot", "Risotto"}


def test_bucket_drops_middle_band() -> None:
    """Items in 14..20d range fall into neither bucket."""
    recently, forgotten = _bucket_recent_meals(
        [{"title": "Mid", "uses": 1, "days_since": 17, "score": 1.0}]
    )
    assert recently == []
    assert forgotten == []


def test_prompt_defaults_smoke() -> None:
    """Default planner produces a structured prompt with all sections."""
    prompt = build_meal_prompt(date(2026, 4, 29), planner=None, recent_items=_items())
    assert "## Context" in prompt
    assert "Doel-datum: Wednesday 29 April 2026" in prompt
    assert "## Recent gegeten" in prompt
    assert "- Spaghetti (2d geleden)" in prompt
    assert "## Vergeten favorieten" in prompt
    assert "Stamppot" in prompt
    # Default cuisines + max_minutes appear
    assert "Max 30 min" in prompt
    assert "Nederlands" in prompt
    # Pantry default appears
    assert "rijst" in prompt
    # Output contract present
    assert "## Output" in prompt


def test_prompt_custom_cuisines_replace_default() -> None:
    """User-provided cuisines fully replace the default list."""
    prompt = build_meal_prompt(
        date(2026, 4, 29),
        planner={
            "ai_task_entity": "ai_task.foo",
            "cuisines": ["Frans", "Spaans"],
        },
    )
    assert "Frans" in prompt
    assert "Spaans" in prompt
    assert "Italiaans" not in prompt


def test_prompt_day_override_thursday() -> None:
    """Day override on target weekday adjusts max_minutes and adds note."""
    prompt = build_meal_prompt(
        date(2026, 4, 30),  # Thursday
        planner={
            "ai_task_entity": "ai_task.foo",
            "day_overrides": {
                "thursday": {
                    "note": "Training om 18:00 — heel makkelijk",
                    "max_minutes": 15,
                }
            },
        },
    )
    assert "Max 15 min" in prompt
    assert "Training om 18:00" in prompt
    assert "Max 30 min" not in prompt


def test_prompt_day_override_other_weekday_not_applied() -> None:
    """Day override only applies on its weekday key."""
    prompt = build_meal_prompt(
        date(2026, 4, 29),  # Wednesday
        planner={
            "ai_task_entity": "ai_task.foo",
            "day_overrides": {"thursday": {"max_minutes": 15}},
        },
    )
    assert "Max 30 min" in prompt
    assert "Max 15 min" not in prompt


def test_prompt_target_date_excluded_from_week() -> None:
    """The target date's own slot is filtered out of the planned-week list."""
    week = [
        {"date": "2026-04-29", "weekday": "Wednesday", "meal": {"title": "Pizza"}},
        {"date": "2026-04-30", "weekday": "Thursday", "meal": {"title": "Soep"}},
    ]
    prompt = build_meal_prompt(
        date(2026, 4, 29),
        planner={"ai_task_entity": "ai_task.foo"},
        week=week,
    )
    assert "Soep" in prompt
    assert "Pizza" not in prompt


def test_prompt_skips_placeholder_meals_in_week() -> None:
    """Placeholder titles in the week list are filtered out."""
    week = [
        {"date": "2026-04-30", "weekday": "Thursday", "meal": {"title": "-"}},
        {"date": "2026-05-01", "weekday": "Friday", "meal": None},
    ]
    prompt = build_meal_prompt(
        date(2026, 4, 29),
        planner={"ai_task_entity": "ai_task.foo"},
        week=week,
    )
    assert "(niets)" in prompt


def test_prompt_extra_notes_appended() -> None:
    """extra_notes block appears verbatim before the Output section."""
    prompt = build_meal_prompt(
        date(2026, 4, 29),
        planner={
            "ai_task_entity": "ai_task.foo",
            "extra_notes": "Sylvia is vandaag niet thuis.",
        },
    )
    assert "Sylvia is vandaag niet thuis." in prompt
    assert prompt.index("Sylvia") < prompt.index("## Output")


def test_prompt_empty_recent_items() -> None:
    """Falls back to '(geen)' when no recent items are available."""
    prompt = build_meal_prompt(
        date(2026, 4, 29),
        planner={"ai_task_entity": "ai_task.foo"},
        recent_items=[],
    )
    # Both buckets render a "(geen)" placeholder
    assert prompt.count("(geen)") == 2
