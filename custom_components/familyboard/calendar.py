"""Proxy calendar entities for FamilyBoard.

Per-member proxies aggregate a member's primary + extra calendars and
filter out Google Tasks. A separate `calendar.familyboard_alles` entity
returns a cross-member deduplicated event stream where multi-member
events expose `members` and `member_colors` metadata via description
markers (so cards can render multi-color borders).
"""

from __future__ import annotations

import logging
from datetime import date as date_cls
from datetime import datetime
from datetime import timedelta as _td

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, TASK_IDENTIFIER, get_device_info

_LOGGER = logging.getLogger(__name__)

# Marker prefix embedded in event description for multi-member events
# Format: [FB:members=Berry,Sylvia;colors=#4A90D9,#27AE60]
MARKER_PREFIX = "[FB:"
MARKER_SUFFIX = "]"

DEFAULT_TRASH_COLORS = {
    "rest": "#555555",
    "paper": "#4A90D9",
    "gft": "#27AE60",
    "pmd": "#F39C12",
}
DEFAULT_TRASH_EMOJIS = {
    "rest": "\U0001f5d1\ufe0f",
    "paper": "\U0001f4c4",
    "gft": "\U0001f33f",
    "pmd": "\u267b\ufe0f",
}


def _build_marker(members: list[str], colors: list[str]) -> str:
    return (
        MARKER_PREFIX
        + "members="
        + ",".join(members)
        + ";colors="
        + ",".join(colors)
        + MARKER_SUFFIX
    )


def _is_task(ev: dict) -> bool:
    return TASK_IDENTIFIER in (ev.get("description") or "")


def _event_key(ev: dict) -> tuple:
    return (
        (ev.get("summary") or "").strip().lower(),
        ev.get("start"),
        ev.get("end"),
    )


def _parse_datetime_or_date(value: str) -> datetime:
    """Parse a datetime or date string into a datetime object."""
    if not value:
        raise ValueError("Empty date string")
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
        return dt
    except ValueError:
        pass
    d = date_cls.fromisoformat(value)
    return datetime.combine(d, datetime.min.time(), tzinfo=dt_util.DEFAULT_TIME_ZONE)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up FamilyBoard proxy calendar entities from a config entry."""
    conf = hass.data[DOMAIN]["config"]
    coordinator = hass.data[DOMAIN]["coordinator"]

    # Build entity_id -> defaults map across all members + extras
    default_descriptions: dict[str, str] = {}
    default_summaries: dict[str, str] = {}
    for member in conf["members"]:
        if member.get("calendar_default_description"):
            default_descriptions[member["calendar"]] = member["calendar_default_description"]
        if member.get("calendar_default_summary"):
            default_summaries[member["calendar"]] = member["calendar_default_summary"]
        for extra in member.get("extra_calendars", []):
            if extra.get("default_description"):
                default_descriptions[extra["entity"]] = extra["default_description"]
            if extra.get("default_summary"):
                default_summaries[extra["entity"]] = extra["default_summary"]

    entities: list[CalendarEntity] = []
    for member in conf["members"]:
        extras = [e["entity"] for e in member.get("extra_calendars", [])]
        entities.append(
            FamilyBoardProxyCalendar(
                coordinator=coordinator,
                member_name=member["name"],
                primary_entity=member["calendar"],
                extra_entities=extras,
                color=member.get("color", "#4A90D9"),
                default_descriptions=default_descriptions,
                default_summaries=default_summaries,
            )
        )

    entities.append(
        FamilyBoardAllesCalendar(
            coordinator,
            conf["members"],
            conf.get("trash", []),
            default_descriptions,
            default_summaries,
        )
    )

    if conf.get("trash"):
        entities.append(FamilyBoardTrashCalendar(coordinator, conf["trash"]))

    async_add_entities(entities, True)


def _build_trash_events(
    hass: HomeAssistant,
    trash: list[dict],
    start_date: datetime,
    end_date: datetime,
) -> list[CalendarEvent]:
    """Read configured trash sensors and emit all-day events in window."""
    events: list[CalendarEvent] = []
    start_d = start_date.date() if isinstance(start_date, datetime) else start_date
    end_d = end_date.date() if isinstance(end_date, datetime) else end_date

    for t in trash:
        sensor_id = t["sensor"]
        ttype = t["type"]
        state = hass.states.get(sensor_id)
        if state is None:
            continue
        raw = state.state
        if not raw or raw in ("unknown", "unavailable", "none"):
            continue
        try:
            d = _parse_datetime_or_date(str(raw)).date()
        except (ValueError, TypeError):
            continue
        if d < start_d or d > end_d:
            continue

        attrs = state.attributes
        label = t.get("label") or attrs.get("label") or ttype.capitalize()
        color = (
            t.get("color")
            or attrs.get("color")
            or DEFAULT_TRASH_COLORS.get(ttype, "#666666")
        )
        emoji = (
            t.get("emoji")
            or attrs.get("emoji")
            or DEFAULT_TRASH_EMOJIS.get(ttype, "\U0001f5d1\ufe0f")
        )

        events.append(
            CalendarEvent(
                summary=f"{emoji} {label}",
                start=d,
                end=d + _td(days=1),
                description=f"[FB:trash={ttype};color={color}]",
            )
        )
    return events


class FamilyBoardProxyCalendar(CoordinatorEntity, CalendarEntity):
    """Proxy that aggregates a member's primary + extra calendars (no tasks)."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator,
        member_name: str,
        primary_entity: str,
        extra_entities: list[str],
        color: str,
        default_descriptions: dict[str, str] | None = None,
        default_summaries: dict[str, str] | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._member_name = member_name
        self._primary_entity = primary_entity
        self._extra_entities = extra_entities
        self._color = color
        self._default_descriptions = default_descriptions or {}
        self._default_summaries = default_summaries or {}
        self._attr_name = member_name
        self._attr_unique_id = f"familyboard_{member_name.lower()}"
        self._attr_device_info = get_device_info()

    @property
    def event(self) -> CalendarEvent | None:
        if not self.coordinator.data:
            return None
        events = self.coordinator.data.get("member_events", {}).get(
            self._member_name, []
        )
        now = dt_util.now()
        for ev in sorted(events, key=lambda e: e.get("start", "")):
            try:
                start_dt = _parse_datetime_or_date(ev.get("start"))
                end_dt = _parse_datetime_or_date(ev.get("end") or ev.get("start"))
                if end_dt >= now:
                    return CalendarEvent(
                        summary=ev.get("summary", ""),
                        start=start_dt,
                        end=end_dt,
                        description=ev.get("description"),
                        location=ev.get("location"),
                    )
            except (ValueError, TypeError):
                continue
        return None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Aggregate primary + extras, filter tasks, dedup within member."""
        all_entities = [self._primary_entity, *self._extra_entities]
        seen: set[tuple] = set()
        out: list[CalendarEvent] = []

        for entity in all_entities:
            raw = await self.coordinator.async_fetch_events(
                entity, start_date.isoformat(), end_date.isoformat()
            )
            default_desc = self._default_descriptions.get(entity)
            default_summary = self._default_summaries.get(entity)
            for ev in raw:
                if _is_task(ev):
                    continue
                key = _event_key(ev)
                if key in seen:
                    continue
                seen.add(key)
                try:
                    start_dt = _parse_datetime_or_date(ev.get("start"))
                    end_dt = _parse_datetime_or_date(
                        ev.get("end") or ev.get("start")
                    )
                except (ValueError, TypeError):
                    continue
                description = ev.get("description") or default_desc
                summary = ev.get("summary") or default_summary or ""
                out.append(
                    CalendarEvent(
                        summary=summary,
                        start=start_dt,
                        end=end_dt,
                        description=description,
                        location=ev.get("location"),
                    )
                )
        return out


class FamilyBoardAllesCalendar(CoordinatorEntity, CalendarEntity):
    """Cross-member deduplicated calendar with multi-member metadata."""

    _attr_has_entity_name = True
    _attr_translation_key = "alles"

    def __init__(
        self,
        coordinator,
        members: list[dict],
        trash: list[dict] | None = None,
        default_descriptions: dict[str, str] | None = None,
        default_summaries: dict[str, str] | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._members = members
        self._trash = trash or []
        self._default_descriptions = default_descriptions or {}
        self._default_summaries = default_summaries or {}
        self._attr_unique_id = "familyboard_alles"
        self._attr_device_info = get_device_info()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if not self._trash:
            return
        sensor_ids = [t["sensor"] for t in self._trash]

        @callback
        def _refresh(_event) -> None:
            self.async_write_ha_state()

        self.async_on_remove(
            async_track_state_change_event(self.hass, sensor_ids, _refresh)
        )

    @property
    def event(self) -> CalendarEvent | None:
        if not self.coordinator.data:
            return None
        events = self.coordinator.data.get("alles_events_today", [])
        now = dt_util.now()
        for ev in events:
            try:
                start_dt = _parse_datetime_or_date(ev.get("start"))
                end_dt = _parse_datetime_or_date(ev.get("end") or ev.get("start"))
                if end_dt >= now:
                    return self._build_event(ev, start_dt, end_dt)
            except (ValueError, TypeError):
                continue
        return None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Query all member calendars (primary+extras), dedup, tag members."""
        bucket: dict[tuple, dict] = {}

        for member in self._members:
            name = member["name"]
            color = member.get("color", "#4A90D9")
            entities = [member["calendar"]] + [
                e["entity"] for e in member.get("extra_calendars", [])
            ]
            seen_for_member: set[tuple] = set()
            for entity in entities:
                raw = await self.coordinator.async_fetch_events(
                    entity, start_date.isoformat(), end_date.isoformat()
                )
                default_desc = self._default_descriptions.get(entity, "")
                default_summary = self._default_summaries.get(entity, "")
                for ev in raw:
                    if _is_task(ev):
                        continue
                    key = _event_key(ev)
                    if key in seen_for_member:
                        continue
                    seen_for_member.add(key)
                    existing = bucket.get(key)
                    if existing is None:
                        bucket[key] = {
                            "summary": ev.get("summary") or default_summary,
                            "start": ev.get("start"),
                            "end": ev.get("end") or ev.get("start"),
                            "description": ev.get("description") or default_desc,
                            "location": ev.get("location") or "",
                            "members": [name],
                            "member_colors": [color],
                        }
                    elif name not in existing["members"]:
                        existing["members"].append(name)
                        existing["member_colors"].append(color)

        out: list[CalendarEvent] = []
        for ev in sorted(bucket.values(), key=lambda e: e.get("start") or ""):
            paired = sorted(zip(ev["members"], ev["member_colors"]))
            ev["members"] = [p[0] for p in paired]
            ev["member_colors"] = [p[1] for p in paired]
            try:
                start_dt = _parse_datetime_or_date(ev["start"])
                end_dt = _parse_datetime_or_date(ev["end"])
            except (ValueError, TypeError):
                continue
            out.append(self._build_event(ev, start_dt, end_dt))

        out.sort(
            key=lambda e: (
                e.start.isoformat() if hasattr(e.start, "isoformat") else str(e.start)
            )
        )
        return out

    def _build_event(
        self, ev: dict, start_dt: datetime, end_dt: datetime
    ) -> CalendarEvent:
        members = ev.get("members") or []
        colors = ev.get("member_colors") or []
        summary = ev.get("summary", "")
        if len(members) > 1 and not summary.startswith("\U0001f465"):
            summary = "\U0001f465 " + summary
        marker = _build_marker(members, colors)
        existing_desc = ev.get("description") or ""
        if existing_desc.startswith(MARKER_PREFIX):
            try:
                end_idx = existing_desc.index(MARKER_SUFFIX) + 1
                existing_desc = existing_desc[end_idx:].lstrip("\n")
            except ValueError:
                pass
        description = marker + ("\n\n" + existing_desc if existing_desc else "")
        return CalendarEvent(
            summary=summary,
            start=start_dt,
            end=end_dt,
            description=description,
            location=ev.get("location") or None,
        )


class FamilyBoardTrashCalendar(CoordinatorEntity, CalendarEntity):
    """Trash-only calendar surfacing configured trash pickup dates."""

    _attr_has_entity_name = True
    _attr_translation_key = "trash"

    def __init__(self, coordinator, trash: list[dict]) -> None:
        super().__init__(coordinator)
        self._trash = trash
        self._attr_unique_id = "familyboard_trash"
        self._attr_device_info = get_device_info()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        sensor_ids = [t["sensor"] for t in self._trash]
        if not sensor_ids:
            return

        @callback
        def _refresh(_event) -> None:
            self.async_write_ha_state()

        self.async_on_remove(
            async_track_state_change_event(self.hass, sensor_ids, _refresh)
        )

    @property
    def event(self) -> CalendarEvent | None:
        events = _build_trash_events(
            self.hass, self._trash, dt_util.now(), dt_util.now() + _td(days=60)
        )
        return events[0] if events else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        return _build_trash_events(hass, self._trash, start_date, end_date)
