"""FamilyBoard integration for Home Assistant.

Consolidates calendar proxy entities (tasks filtered out), a chores sensor,
add-event service, snooze reminder engine, trash chore auto-creation, and
custom Lovelace cards into one component.

Configured via YAML in `configuration.yaml`; an empty config entry is
created automatically so a device + entities can be registered.
"""

from __future__ import annotations

from datetime import datetime as _dt, time, timedelta
import hashlib
import logging
from pathlib import Path
from typing import Any

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util
import voluptuous as vol

from .const import (
    DAY_END_ENTITY,
    DAY_START_ENTITY,
    DEVICE_IDENTIFIER,
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DEVICE_NAME,
    DOMAIN,
    EVENT_ALL_DAY_ENTITY,
    EVENT_CALENDAR_ENTITY,
    EVENT_END_ENTITY,
    EVENT_MEMBER_ENTITY,
    EVENT_START_ENTITY,
    EVENT_TITLE_ENTITY,
    MEAL_LOOKAHEAD_DAYS,
    SCAN_INTERVAL_MINUTES,
    TASK_IDENTIFIER,
    VIEW_ENTITY,
)
from .helpers import member_calendar_entities
from .reminder import ReminderManager
from .schemas import OPTIONS_SCHEMA, default_options
from .trash import TrashChoreManager

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.CALENDAR,
    Platform.SENSOR,
    Platform.SELECT,
    Platform.TEXT,
    Platform.SWITCH,
    Platform.DATETIME,
]

# (resource_id, filename) — registered as Lovelace module resources
_FRONTEND_RESOURCES: list[tuple[str, str]] = [
    ("familyboard_card", "familyboard-chores-card.js"),
    ("familyboard_filter_card", "familyboard-filter-card.js"),
    ("familyboard_calendar_card", "familyboard-calendar-card.js"),
    ("familyboard_progress_card", "familyboard-progress-card.js"),
    ("familyboard_strategy", "familyboard-strategy.js"),
]

# ---------------------------------------------------------------------------
# Configuration schemas (CONFIG_SCHEMA pulls from .schemas for runtime parts)
# ---------------------------------------------------------------------------

CONFIG_SCHEMA = vol.Schema(
    {DOMAIN: OPTIONS_SCHEMA},
    extra=vol.ALLOW_EXTRA,
)

ADD_EVENT_SCHEMA = vol.Schema({})
SNOOZE_TEST_SCHEMA = vol.Schema({vol.Required("uid"): cv.string})
CANCEL_REMINDER_SCHEMA = vol.Schema({vol.Required("uid"): cv.string})


# ---------------------------------------------------------------------------
# Setup / unload
# ---------------------------------------------------------------------------


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Validate YAML config and trigger config entry import (one-time).

    YAML keeps working but the source of truth at runtime is
    ``entry.options``. The import flow seeds options from YAML on first run
    and refreshes them on subsequent restarts.
    """
    if DOMAIN not in config:
        return True

    yaml_conf = config[DOMAIN]
    hass.data.setdefault(DOMAIN, {})["yaml_config"] = yaml_conf

    hass.async_create_task(
        hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_IMPORT}, data=yaml_conf
        )
    )
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the integration when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up FamilyBoard from a config entry."""
    fb = hass.data.setdefault(DOMAIN, {})

    # Prefer entry.options; fall back to YAML for legacy installs that haven't
    # been re-imported yet.
    if entry.options:
        conf = dict(entry.options)
    else:
        conf = fb.get("yaml_config") or default_options()

    # Make sure required keys exist
    for key in ("members", "trash", "shared_calendars", "shared_chores"):
        conf.setdefault(key, [])

    if not conf.get("members"):
        _LOGGER.warning(
            "FamilyBoard has no members configured; entities will be empty. "
            "Add members via Configuration \u2192 Devices & Services \u2192 "
            "FamilyBoard \u2192 Configure."
        )

    fb["config"] = conf

    # Register the shared device against this entry
    dev_reg = dr.async_get(hass)
    dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={DEVICE_IDENTIFIER},
        name=DEVICE_NAME,
        manufacturer=DEVICE_MANUFACTURER,
        model=DEVICE_MODEL,
        entry_type=dr.DeviceEntryType.SERVICE,
    )

    # Reminder + trash auto-chore engines
    reminder_manager = ReminderManager(hass, conf["members"])
    fb["reminder_manager"] = reminder_manager

    trash_chore_manager = TrashChoreManager(
        hass, conf.get("trash", []), conf.get("shared_chores", [])
    )
    fb["trash_chore_manager"] = trash_chore_manager

    # Coordinator (first refresh delayed until HA fully started)
    coordinator = FamilyBoardCoordinator(
        hass, conf, reminder_manager, trash_chore_manager
    )
    fb["coordinator"] = coordinator

    # Services
    _async_register_services(hass, conf)

    # Forward to platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Reload the entry whenever the options flow saves changes
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    # Late init: register frontend, link entities, run first refresh
    async def _async_startup(_event: Any = None) -> None:
        """Run frontend + entity wiring + initial refresh once HA is ready."""
        await _async_register_frontend(hass)
        await _async_link_entities(hass, entry)
        await reminder_manager.async_start()
        await trash_chore_manager.async_start()
        await coordinator.async_refresh()
        await _async_check_lovelace_dependencies(hass)

    if hass.is_running:
        hass.async_create_task(_async_startup())
    else:
        entry.async_on_unload(
            hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _async_startup)
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry: stop managers, deregister services, unload platforms."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    fb = hass.data.get(DOMAIN, {})

    reminder_manager: ReminderManager | None = fb.get("reminder_manager")
    if reminder_manager is not None:
        await reminder_manager.async_stop()

    trash_chore_manager: TrashChoreManager | None = fb.get("trash_chore_manager")
    if trash_chore_manager is not None:
        await trash_chore_manager.async_stop()

    for svc in ("add_event", "snooze_test", "cancel_reminder"):
        if hass.services.has_service(DOMAIN, svc):
            hass.services.async_remove(DOMAIN, svc)

    # Keep `config` so a YAML reload can re-create the entry without reload of HA
    fb.pop("reminder_manager", None)
    fb.pop("trash_chore_manager", None)
    fb.pop("coordinator", None)
    fb.pop("select", None)
    fb.pop("text", None)
    fb.pop("switch", None)
    fb.pop("datetime", None)

    return True


async def _async_link_entities(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Ensure all FB entities are linked to our device + this entry."""
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_device(identifiers={DEVICE_IDENTIFIER})
    if device is None:
        return

    ent_reg = er.async_get(hass)
    for ent in list(ent_reg.entities.values()):
        if ent.platform != DOMAIN:
            continue
        updates: dict[str, Any] = {}
        if ent.device_id != device.id:
            updates["device_id"] = device.id
        if ent.config_entry_id != entry.entry_id:
            updates["config_entry_id"] = entry.entry_id
        if updates:
            ent_reg.async_update_entity(ent.entity_id, **updates)


# ---------------------------------------------------------------------------
# Frontend resource registration (Lovelace)
# ---------------------------------------------------------------------------


def _get_js_version(filename: str) -> str:
    """Return a short SHA256-based version hash for cache busting."""
    js_path = Path(__file__).parent / "frontend" / filename
    try:
        content = js_path.read_bytes()
    except OSError as err:
        _LOGGER.debug("Could not read %s for versioning: %s", js_path, err)
        return "1"
    return hashlib.sha256(content).hexdigest()[:8]


async def _async_register_frontend(hass: HomeAssistant) -> None:
    """Register the custom card JS via the static path + Lovelace resources API."""
    frontend_dir = Path(__file__).parent / "frontend"
    await hass.http.async_register_static_paths(
        [StaticPathConfig("/familyboard", str(frontend_dir), False)]
    )
    await _async_sync_lovelace_resources(hass)


async def _async_sync_lovelace_resources(hass: HomeAssistant) -> None:
    """Create or update Lovelace resource entries for our cards."""
    lovelace_data = hass.data.get("lovelace")
    if lovelace_data is None:
        _LOGGER.debug("Lovelace not loaded yet; skipping resource registration")
        return

    resources = getattr(lovelace_data, "resources", None)
    if resources is None:
        _LOGGER.debug("Lovelace resources collection unavailable")
        return

    if not resources.loaded:
        try:
            await resources.async_load()
        except HomeAssistantError as err:
            _LOGGER.warning("Could not load Lovelace resources: %s", err)
            return

    # Build url -> existing resource map (by filename match, regardless of ?v=...)
    existing_by_path: dict[str, dict[str, Any]] = {}
    for item in list(resources.async_items()):
        url = item.get("url", "")
        path = url.split("?", 1)[0]
        existing_by_path[path] = item

    for _res_id, fname in _FRONTEND_RESOURCES:
        version = _get_js_version(fname)
        path = f"/familyboard/{fname}"
        target_url = f"{path}?v={version}"
        existing = existing_by_path.get(path)
        try:
            if existing is None:
                await resources.async_create_item(
                    {"res_type": "module", "url": target_url}
                )
                _LOGGER.info("Registered Lovelace resource: %s", target_url)
            elif existing.get("url") != target_url:
                await resources.async_update_item(
                    existing["id"],
                    {"res_type": "module", "url": target_url},
                )
                _LOGGER.info("Updated Lovelace resource: %s", target_url)
        except HomeAssistantError as err:
            _LOGGER.warning(
                "Could not register Lovelace resource %s: %s", target_url, err
            )


async def _async_check_lovelace_dependencies(hass: HomeAssistant) -> None:
    """Warn if required HACS frontend deps (mushroom, card-mod) are missing."""
    required = {"mushroom": "Mushroom Cards", "card-mod": "card-mod"}
    found: set[str] = set()

    lovelace_data = hass.data.get("lovelace")
    resources = getattr(lovelace_data, "resources", None) if lovelace_data else None
    if resources is None:
        return
    if not resources.loaded:
        try:
            await resources.async_load()
        except HomeAssistantError:
            return

    for item in resources.async_items():
        url = (item.get("url") or "").lower()
        for key in required:
            if key in url:
                found.add(key)

    missing = [name for key, name in required.items() if key not in found]
    if not missing:
        return

    msg = (
        "FamilyBoard requires the following Lovelace resources (install via HACS): "
        + ", ".join(missing)
    )
    _LOGGER.warning(msg)
    try:
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "FamilyBoard: missing dependencies",
                "message": msg,
                "notification_id": "familyboard_missing_deps",
            },
            blocking=False,
        )
    except HomeAssistantError as err:
        _LOGGER.debug("Could not create persistent_notification: %s", err)


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------


def _async_register_services(hass: HomeAssistant, conf: dict) -> None:
    """Register the familyboard.* services."""
    cal_map: dict[tuple[str, str], str] = {}
    for member in conf["members"]:
        for label, entity in member_calendar_entities(member):
            cal_map[(member["name"], label)] = entity

    async def handle_add_event(call: ServiceCall) -> None:
        """Create a calendar event from the add-event form entities."""
        member_state = hass.states.get(EVENT_MEMBER_ENTITY)
        calendar_state = hass.states.get(EVENT_CALENDAR_ENTITY)
        title = hass.states.get(EVENT_TITLE_ENTITY)
        all_day = hass.states.get(EVENT_ALL_DAY_ENTITY)

        if not member_state or not calendar_state or not title:
            raise HomeAssistantError("Missing entity states for add_event")

        target_calendar = cal_map.get((member_state.state, calendar_state.state))
        if not target_calendar:
            raise HomeAssistantError(
                f"Unknown calendar: member={member_state.state} "
                f"label={calendar_state.state}"
            )

        event_title = title.state
        if not event_title or event_title in ("unknown", "unavailable"):
            _LOGGER.debug("Empty event title; skipping add_event")
            return

        if all_day and all_day.state == "on":
            start = hass.states.get(DAY_START_ENTITY)
            end = hass.states.get(DAY_END_ENTITY)
            if start and end:
                await hass.services.async_call(
                    "calendar",
                    "create_event",
                    {
                        "summary": event_title,
                        "start_date": start.state[:10],
                        "end_date": end.state[:10],
                    },
                    target={"entity_id": target_calendar},
                    blocking=True,
                )
        else:
            start = hass.states.get(EVENT_START_ENTITY)
            end = hass.states.get(EVENT_END_ENTITY)
            if start and end:
                await hass.services.async_call(
                    "calendar",
                    "create_event",
                    {
                        "summary": event_title,
                        "start_date_time": start.state,
                        "end_date_time": end.state,
                    },
                    target={"entity_id": target_calendar},
                    blocking=True,
                )

        # Reset form
        await hass.services.async_call(
            "text",
            "set_value",
            {"entity_id": EVENT_TITLE_ENTITY, "value": ""},
            blocking=True,
        )
        await hass.services.async_call(
            "switch",
            "turn_off",
            {"entity_id": EVENT_ALL_DAY_ENTITY},
            blocking=True,
        )

    async def handle_snooze_test(call: ServiceCall) -> None:
        """Force-fire a reminder by uid for testing."""
        manager: ReminderManager | None = hass.data.get(DOMAIN, {}).get(
            "reminder_manager"
        )
        if manager is None:
            return
        uid = call.data["uid"]
        await manager.async_test_fire(uid)

    async def handle_cancel_reminder(call: ServiceCall) -> None:
        """Cancel an active reminder by uid."""
        manager: ReminderManager | None = hass.data.get(DOMAIN, {}).get(
            "reminder_manager"
        )
        if manager is None:
            return
        uid = call.data["uid"]
        await manager.async_cancel(uid)

    hass.services.async_register(
        DOMAIN, "add_event", handle_add_event, schema=ADD_EVENT_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "snooze_test", handle_snooze_test, schema=SNOOZE_TEST_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "cancel_reminder", handle_cancel_reminder, schema=CANCEL_REMINDER_SCHEMA
    )


# ---------------------------------------------------------------------------
# Coordinator
# ---------------------------------------------------------------------------


class FamilyBoardCoordinator(DataUpdateCoordinator):
    """Coordinator that fetches calendar events and todo items."""

    def __init__(
        self,
        hass: HomeAssistant,
        conf: dict,
        reminder_manager: ReminderManager | None = None,
        trash_chore_manager: TrashChoreManager | None = None,
    ) -> None:
        """Initialize the coordinator with config + optional managers."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=SCAN_INTERVAL_MINUTES),
        )
        self.conf = conf
        self.members = conf["members"]
        self.reminder_manager = reminder_manager
        self.trash_chore_manager = trash_chore_manager
        self._prev_active_uids: dict[str, set[str]] = {}
        self._daily_completed: dict[str, int] = {}
        self._progress_date: str = ""

    async def async_fetch_events(
        self, entity_id: str, start_iso: str, end_iso: str
    ) -> list[dict]:
        """Public helper used by calendar entities to fetch events."""
        return await self._fetch_events(entity_id, start_iso, end_iso)

    async def _fetch_events(
        self, entity_id: str, start_iso: str, end_iso: str
    ) -> list[dict]:
        """Call ``calendar.get_events`` and return the raw event list."""
        try:
            response = await self.hass.services.async_call(
                "calendar",
                "get_events",
                {"start_date_time": start_iso, "end_date_time": end_iso},
                target={"entity_id": entity_id},
                blocking=True,
                return_response=True,
            )
        except HomeAssistantError:
            _LOGGER.exception("Error fetching events from %s", entity_id)
            return []
        if not response or entity_id not in response:
            return []
        return response[entity_id].get("events", [])

    async def _fetch_todo_items(
        self, entity_id: str, status: str = "needs_action"
    ) -> list[dict]:
        """Call ``todo.get_items`` for ``entity_id`` filtered by status."""
        try:
            response = await self.hass.services.async_call(
                "todo",
                "get_items",
                {"status": [status]},
                target={"entity_id": entity_id},
                blocking=True,
                return_response=True,
            )
        except HomeAssistantError:
            _LOGGER.exception("Error fetching todos from %s", entity_id)
            return []
        if not response or entity_id not in response:
            return []
        return response[entity_id].get("items", [])

    def _get_view_window(self, now: _dt) -> tuple[str, str] | None:
        """Return (start, end) ISO date pair for the current view selection."""
        view_state = self.hass.states.get(VIEW_ENTITY)
        if not view_state:
            return None
        view = view_state.state
        today = now.date()
        if view == "Vandaag":
            return (today.isoformat(), today.isoformat())
        if view == "Morgen":
            return (today.isoformat(), (today + timedelta(days=1)).isoformat())
        if view == "Week":
            return (today.isoformat(), (today + timedelta(days=7)).isoformat())
        if view == "2 Weken":
            return (today.isoformat(), (today + timedelta(days=14)).isoformat())
        if view == "Maand":
            return (today.isoformat(), (today + timedelta(days=30)).isoformat())
        return None

    def _chore_in_view(self, chore: dict, view_window: tuple[str, str] | None) -> bool:
        """Return True if the chore's due date falls inside the view window."""
        if view_window is None:
            return True
        due = chore.get("due")
        if not due:
            return True
        if due < view_window[0]:
            return True
        return view_window[0] <= due <= view_window[1]

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch calendar events + chores; build dedup'd cross-member view."""
        now = dt_util.now()
        today_start = _dt.combine(now.date(), time.min, tzinfo=now.tzinfo)
        today_end = _dt.combine(now.date(), time.max, tzinfo=now.tzinfo)
        tasks_start = today_start - timedelta(days=7)
        tasks_end = today_end + timedelta(days=14)
        today_str = now.date().isoformat()

        view_window = self._get_view_window(now)

        result: dict[str, Any] = {
            "member_events": {},
            "member_chores": {},
            "members_meta": [],
            "alles_events_today": [],
            "shared_calendars": list(self.conf.get("shared_calendars", [])),
            "shared_chores": list(self.conf.get("shared_chores", [])),
            "progress": {},
        }

        alles_map: dict[tuple, dict] = {}
        member_meta: dict[str, dict] = {}

        for member in self.members:
            name = member["name"]
            primary_entity = member["calendar"]
            chore_entities = member.get("chores", [])
            color = member.get("color", "#4A90D9")
            person_entity = member.get("person")
            picture = None
            if person_entity:
                state = self.hass.states.get(person_entity)
                if state:
                    picture = state.attributes.get("entity_picture")

            member_meta[name] = {
                "color": color,
                "picture": picture,
                "chore_entities": chore_entities,
            }

            result["members_meta"].append(
                {
                    "name": name,
                    "color": color,
                    "picture": picture,
                    "person": person_entity,
                    "calendar": primary_entity,
                }
            )

            primary_events = await self._fetch_events(
                primary_entity, tasks_start.isoformat(), tasks_end.isoformat()
            )

            task_events: list[dict] = []
            real_events: list[dict] = []
            for ev in primary_events:
                desc = ev.get("description") or ""
                (task_events if TASK_IDENTIFIER in desc else real_events).append(ev)

            extra_events: list[dict] = []
            for extra in member.get("extra_calendars", []):
                extra_events.extend(
                    await self._fetch_events(
                        extra["entity"],
                        today_start.isoformat(),
                        today_end.isoformat(),
                    )
                )

            all_events = real_events + extra_events

            today_events_raw = [
                e
                for e in all_events
                if (
                    e.get("start", "")[:10] <= today_str
                    and e.get("end", "")[:10] >= today_str
                )
                or e.get("start", "")[:10] == today_str
            ]

            seen_keys: set[tuple] = set()
            today_events: list[dict] = []
            for e in today_events_raw:
                key = (
                    (e.get("summary") or "").strip().lower(),
                    e.get("start"),
                    e.get("end"),
                )
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                today_events.append(e)

                existing = alles_map.get(key)
                if existing is None:
                    alles_map[key] = {
                        "summary": e.get("summary", ""),
                        "start": e.get("start"),
                        "end": e.get("end"),
                        "description": e.get("description", ""),
                        "location": e.get("location", ""),
                        "members": [name],
                        "member_colors": [color],
                    }
                elif name not in existing["members"]:
                    existing["members"].append(name)
                    existing["member_colors"].append(color)

            result["member_events"][name] = today_events

            chores: list[dict[str, Any]] = []
            all_todo_items: list[tuple[str, dict]] = []
            for chore_entity in chore_entities:
                items = await self._fetch_todo_items(chore_entity)
                for item in items:
                    all_todo_items.append((chore_entity, item))

            cal_task_map: dict[str, list[dict]] = {}
            for cal_task in task_events:
                key2 = (cal_task.get("summary") or "").strip().lower()
                if key2:
                    cal_task_map.setdefault(key2, []).append(cal_task)

            matched_cal_indices: set[tuple[str, int]] = set()

            for todo_ent, todo_item in all_todo_items:
                todo_summary = todo_item.get("summary", "")
                if not todo_summary:
                    continue
                todo_uid = todo_item.get("uid", "")
                todo_due = todo_item.get("due")
                norm_summary = todo_summary.strip().lower()

                matched_cal: dict | None = None
                matched_idx = -1
                for idx, cal_task in enumerate(cal_task_map.get(norm_summary, [])):
                    cal_key = (norm_summary, idx)
                    if cal_key in matched_cal_indices:
                        continue
                    if (
                        todo_due
                        and cal_task.get("start")
                        and cal_task["start"][:10] != todo_due[:10]
                    ):
                        continue
                    matched_cal = cal_task
                    matched_idx = idx
                    break

                if matched_cal is not None:
                    matched_cal_indices.add((norm_summary, matched_idx))

                chores.append(
                    {
                        "summary": todo_summary,
                        "start": matched_cal.get("start") if matched_cal else None,
                        "end": matched_cal.get("end") if matched_cal else None,
                        "due": todo_due,
                        "description": todo_item.get("description", ""),
                        "member": name,
                        "color": color,
                        "picture": picture,
                        "todo_entity": todo_ent,
                        "uid": todo_uid,
                        "completed": False,
                    }
                )

            result["member_chores"][name] = chores

        # Shared chores: fan out to each listed member
        for shared in self.conf.get("shared_chores", []):
            shared_entity = shared["entity"]
            shared_members = shared["members"]
            shared_name = shared.get("name", "")
            shared_color = shared.get("color", "")

            items = await self._fetch_todo_items(shared_entity)
            for todo_item in items:
                todo_summary = todo_item.get("summary", "")
                if not todo_summary:
                    continue
                for mname in shared_members:
                    if mname not in result["member_chores"]:
                        continue
                    meta = member_meta.get(mname, {})
                    existing_uids = {
                        c.get("uid")
                        for c in result["member_chores"][mname]
                        if c.get("uid")
                    }
                    if todo_item.get("uid") and todo_item["uid"] in existing_uids:
                        continue
                    result["member_chores"][mname].append(
                        {
                            "summary": todo_summary,
                            "start": None,
                            "end": None,
                            "due": todo_item.get("due"),
                            "description": todo_item.get("description", ""),
                            "member": mname,
                            "color": meta.get("color", "#4A90D9"),
                            "picture": meta.get("picture"),
                            "todo_entity": shared_entity,
                            "uid": todo_item.get("uid"),
                            "completed": False,
                            "shared": True,
                            "shared_members": shared_members,
                            "shared_name": shared_name,
                            "shared_color": shared_color,
                        }
                    )

        # Combine + dedup + filter by view window
        all_chores: list[dict] = []
        for chores_list in result["member_chores"].values():
            for chore in chores_list:
                if self._chore_in_view(chore, view_window):
                    all_chores.append(chore)

        seen_uids: set[str] = set()
        deduped_chores: list[dict] = []
        for chore in all_chores:
            uid = chore.get("uid")
            if uid and chore.get("shared") and uid in seen_uids:
                continue
            if uid:
                seen_uids.add(uid)
            deduped_chores.append(chore)

        def _sort_key(chore: dict) -> tuple:
            """Sort overdue first, then by due date, then no-date last."""
            due = chore.get("due")
            if due and due < today_str:
                return (0, due)
            if due:
                return (1, due)
            return (2, "")

        deduped_chores.sort(key=_sort_key)
        result["all_chores_sorted"] = deduped_chores

        # Daily-progress tracking
        if self._progress_date != today_str:
            self._progress_date = today_str
            self._daily_completed = {}
            self._prev_active_uids = {}

        for member in self.members:
            mname = member["name"]
            current_uids: set[str] = {
                c["uid"]
                for c in result["member_chores"].get(mname, [])
                if c.get("uid") and self._chore_in_view(c, view_window)
            }
            prev_uids = self._prev_active_uids.get(mname, set())
            disappeared = prev_uids - current_uids
            if disappeared:
                self._daily_completed[mname] = self._daily_completed.get(
                    mname, 0
                ) + len(disappeared)
            self._prev_active_uids[mname] = current_uids

            completed = self._daily_completed.get(mname, 0)
            active = len(
                [
                    c
                    for c in result["member_chores"].get(mname, [])
                    if self._chore_in_view(c, view_window)
                ]
            )
            result["progress"][mname] = {
                "total": active + completed,
                "completed": completed,
            }

        for ev in alles_map.values():
            paired = sorted(zip(ev["members"], ev["member_colors"], strict=False))
            ev["members"] = [p[0] for p in paired]
            ev["member_colors"] = [p[1] for p in paired]

        result["alles_events_today"] = sorted(
            alles_map.values(), key=lambda e: e.get("start") or ""
        )

        if self.trash_chore_manager:
            try:
                await self.trash_chore_manager.async_auto_complete()
            except HomeAssistantError:
                _LOGGER.exception("Trash chore auto-complete failed")

        if self.reminder_manager:
            try:
                self.reminder_manager.sync_from_chores(deduped_chores)
            except HomeAssistantError:
                _LOGGER.exception("Reminder sync failed")

        result["meals"] = await self._fetch_meals(now)

        return result

    async def _fetch_meals(self, now: _dt) -> list[dict]:
        """Fetch upcoming meals from the configured ``meal_calendar``.

        Returns a list of ``{date, title, start, end, description, uid,
        all_day}`` ordered by start. Empty list when no meal calendar is
        configured or the calendar entity yields nothing.
        """
        meal_entity = self.conf.get("meal_calendar")
        if not meal_entity:
            return []

        today = now.date()
        window_start = _dt.combine(today, time.min, tzinfo=now.tzinfo)
        window_end = _dt.combine(
            today + timedelta(days=MEAL_LOOKAHEAD_DAYS),
            time.max,
            tzinfo=now.tzinfo,
        )
        events = await self._fetch_events(
            meal_entity, window_start.isoformat(), window_end.isoformat()
        )

        meals: list[dict] = []
        for ev in events:
            start = ev.get("start") or ""
            end = ev.get("end") or ""
            date = start[:10] if start else ""
            if not date:
                continue
            meals.append(
                {
                    "date": date,
                    "title": ev.get("summary", ""),
                    "start": start,
                    "end": end,
                    "description": ev.get("description", ""),
                    "uid": ev.get("uid", ""),
                    "all_day": "T" not in start,
                }
            )
        meals.sort(key=lambda m: m["start"])
        return meals
