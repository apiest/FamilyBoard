"""Shared helpers used across FamilyBoard modules."""

from __future__ import annotations

from datetime import date as _date
from itertools import pairwise
from typing import Any

from .const import (
    DEFAULT_MEAL_CUISINES,
    DEFAULT_MEAL_MAX_MINUTES,
    DEFAULT_MEAL_PANTRY,
    DEFAULT_MEAL_RESTRICTIONS,
    MEAL_AVOID_DAYS,
    MEAL_EMPTY_TITLES,
    MEAL_FAVORITE_DAYS,
    MEAL_PENALTY_ANCHORS,
    MEAL_PICKER_LIMIT,
)


def is_meal_placeholder(title: str | None) -> bool:
    """Return True when the meal title means 'deliberately no meal'."""
    if title is None:
        return True
    return title.strip().lower() in MEAL_EMPTY_TITLES


def meal_penalty(days_since: int) -> float:
    """Linear-interpolated penalty by days since last use; 30+ → 0."""
    anchors = MEAL_PENALTY_ANCHORS
    if days_since <= anchors[0][0]:
        return anchors[0][1]
    if days_since >= anchors[-1][0]:
        return anchors[-1][1]
    for (d0, p0), (d1, p1) in pairwise(anchors):
        if d0 <= days_since <= d1:
            if d1 == d0:
                return p0
            ratio = (days_since - d0) / (d1 - d0)
            return p0 + (p1 - p0) * ratio
    return 0.0


def score_recent_meals(
    events: list[dict[str, Any]],
    today: _date,
) -> list[dict[str, Any]]:
    """Return scored, deduped recent meal titles sorted by score desc.

    ``events`` items must have ``title`` and ``date`` (ISO yyyy-mm-dd).
    Placeholders are skipped. Result is capped at ``MEAL_PICKER_LIMIT``.
    """
    grouped: dict[str, dict[str, Any]] = {}
    for ev in events:
        title = (ev.get("title") or "").strip()
        if is_meal_placeholder(title):
            continue
        key = title.lower()
        try:
            ev_date = _date.fromisoformat(ev["date"])
        except (KeyError, ValueError):
            continue
        entry = grouped.get(key)
        if entry is None:
            grouped[key] = {
                "title": title,
                "uses": 1,
                "last_used": ev_date,
            }
        else:
            entry["uses"] += 1
            if ev_date > entry["last_used"]:
                entry["last_used"] = ev_date
                entry["title"] = title  # keep most-recent capitalisation

    items: list[dict[str, Any]] = []
    for entry in grouped.values():
        days_since = (today - entry["last_used"]).days
        score = entry["uses"] - meal_penalty(days_since)
        items.append(
            {
                "title": entry["title"],
                "uses": entry["uses"],
                "last_used": entry["last_used"].isoformat(),
                "days_since": days_since,
                "score": round(score, 2),
            }
        )

    items.sort(key=lambda i: (i["score"], -i["days_since"]), reverse=True)
    return items[:MEAL_PICKER_LIMIT]


def primary_label(member: dict[str, Any]) -> str:
    """Return the label used for a member's primary calendar."""
    return member.get("calendar_label") or f"{member['name']} priv\u00e9"


def member_calendar_labels(member: dict[str, Any]) -> list[str]:
    """Return ordered list of all calendar labels for a member."""
    labels = [primary_label(member)]
    for extra in member.get("extra_calendars", []):
        labels.append(extra["label"])
    return labels


def member_calendar_entities(member: dict[str, Any]) -> list[tuple[str, str]]:
    """Return [(label, entity_id), ...] for primary + extras."""
    out = [(primary_label(member), member["calendar"])]
    for extra in member.get("extra_calendars", []):
        out.append((extra["label"], extra["entity"]))
    return out


# ---------------------------------------------------------------------------
# Meal suggestion prompt builder (Phase 2.5)
# ---------------------------------------------------------------------------


def _bucket_recent_meals(
    items: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split scored recent-meal items into (recently_eaten, forgotten_favorites).

    ``recently_eaten`` = items with ``days_since < MEAL_AVOID_DAYS``,
    sorted ascending by ``days_since`` (most recent first) — these are
    the meals to AVOID re-suggesting.

    ``forgotten_favorites`` = items with ``days_since >= MEAL_FAVORITE_DAYS``,
    keeping the input order (which is score-desc) — these are inspiration.
    """
    recently: list[dict[str, Any]] = []
    forgotten: list[dict[str, Any]] = []
    for item in items:
        days = item.get("days_since")
        if days is None:
            continue
        if days < MEAL_AVOID_DAYS:
            recently.append(item)
        elif days >= MEAL_FAVORITE_DAYS:
            forgotten.append(item)
    recently.sort(key=lambda i: i["days_since"])
    return recently, forgotten


def build_meal_prompt(
    target_date: _date,
    *,
    planner: dict[str, Any] | None,
    recent_items: list[dict[str, Any]] | None = None,
    week: list[dict[str, Any]] | None = None,
) -> str:
    """Render the AI meal-suggestion prompt for ``target_date``.

    ``planner`` is the ``meal_planner`` options block (may be ``None``;
    defaults are applied per missing key). ``recent_items`` mirrors the
    ``items`` attribute of ``sensor.familyboard_recent_meals``. ``week``
    mirrors the ``week`` attribute of ``sensor.familyboard_meals``; the
    ``target_date`` entry is filtered out so the model does not see its
    own slot as "already planned".
    """
    planner = planner or {}
    cuisines = list(planner.get("cuisines") or DEFAULT_MEAL_CUISINES)
    pantry = list(planner.get("pantry_staples") or DEFAULT_MEAL_PANTRY)
    restrictions = list(planner.get("restrictions") or DEFAULT_MEAL_RESTRICTIONS)
    max_minutes = planner.get("max_minutes") or DEFAULT_MEAL_MAX_MINUTES
    overrides = planner.get("day_overrides") or {}
    extra_notes = (planner.get("extra_notes") or "").strip()

    weekday_en = target_date.strftime("%A")
    override = overrides.get(weekday_en.lower()) or {}
    if "max_minutes" in override:
        max_minutes = override["max_minutes"]
    day_note = (override.get("note") or "").strip()

    target_iso = target_date.isoformat()
    target_human = target_date.strftime("%A %d %B %Y")

    recently_eaten, forgotten_favorites = _bucket_recent_meals(recent_items or [])

    lines: list[str] = []
    lines.append(
        "Je bent een huiskok die avondmaaltijden plant voor een Nederlands gezin."
    )
    lines.append("")
    lines.append("## Context")
    lines.append(f"Doel-datum: {target_human}")
    lines.append(f"Dag van de week: {weekday_en}")
    lines.append("")

    lines.append("## Recent gegeten — NIET opnieuw voorstellen")
    if recently_eaten:
        for m in recently_eaten[:10]:
            lines.append(f"- {m['title']} ({m['days_since']}d geleden)")
    else:
        lines.append("- (geen)")
    lines.append("")

    lines.append("## Vergeten favorieten — overweeg deze als inspiratie")
    if forgotten_favorites:
        for m in forgotten_favorites[:8]:
            lines.append(
                f"- {m['title']} (laatst {m['days_since']}d geleden, "
                f"{m['uses']}\u00d7 in 90d)"
            )
    else:
        lines.append("- (geen)")
    lines.append("")

    lines.append("## Al gepland deze week (vermijd herhaling)")
    week_lines: list[str] = []
    for entry in week or []:
        if entry.get("date") == target_iso:
            continue
        meal = entry.get("meal")
        if not meal:
            continue
        title = meal.get("title") or ""
        if not title or is_meal_placeholder(title):
            continue
        week_lines.append(f"- {entry['date']} ({entry.get('weekday', '')}): {title}")
    if week_lines:
        lines.extend(week_lines)
    else:
        lines.append("- (niets)")
    lines.append("")

    lines.append("## Harde regels")
    for r in restrictions:
        lines.append(f"- {r}")
    lines.append(f"- Max {max_minutes} min totale bereidingstijd")
    lines.append("- Gezinsvriendelijk, niet te pittig")
    if cuisines:
        lines.append(
            "- Variatie in keukens is welkom: "
            + ", ".join(cuisines)
            + ". Wissel af; stel niet twee dagen achter elkaar dezelfde keuken voor."
        )
    if day_note:
        lines.append(f"- {day_note}")
    lines.append("")

    lines.append("## Boodschappen-regel")
    lines.append(
        "Neem in `ingredients` ALLEEN producten op die normaal NIET in een "
        "Nederlandse voorraadkast/koelkast liggen."
    )
    if pantry:
        lines.append("Sla over: " + ", ".join(pantry) + ".")
    lines.append(
        'Geen hoeveelheden, geen merken, alleen het product (bv. "kipfilet", '
        '"verse basilicum").'
    )
    lines.append("")

    if extra_notes:
        lines.append("## Extra")
        lines.append(extra_notes)
        lines.append("")

    lines.append("## Output")
    lines.append("Antwoord uitsluitend met de JSON-velden uit het schema.")
    lines.append("Geen uitleg, geen recept, geen stappen.")

    return "\n".join(lines)
