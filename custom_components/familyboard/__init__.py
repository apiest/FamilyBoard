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
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util
import voluptuous as vol

from .caldav_client import CalDAVClientManager
from .const import (
    CHORE_CLAIM_STORAGE_KEY,
    CHORE_CLAIM_STORAGE_VERSION,
    CHORE_HISTORY_MAX_DAYS,
    CHORE_HISTORY_MAX_ENTRIES,
    CHORE_HISTORY_STORAGE_KEY,
    CHORE_HISTORY_STORAGE_VERSION,
    CONFIG_ENTRY_VERSION,
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
    MEAL_RECENT_WINDOW_DAYS,
    MEAL_SUGGESTION_STORAGE_KEY,
    MEAL_SUGGESTION_STORAGE_VERSION,
    SCAN_INTERVAL_MINUTES,
    TASK_IDENTIFIER,
    VIEW_ENTITY,
)
from .helpers import (
    build_meal_prompt,
    is_meal_placeholder,
    member_calendar_entities,
    score_recent_meals,
)
from .reminder import ReminderManager
from .schemas import OPTIONS_SCHEMA, default_options
from .subentries import compose_conf, migrate_options_to_subentries
from .trash import TrashChoreManager

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.CALENDAR,
    Platform.SENSOR,
    Platform.SELECT,
    Platform.TEXT,
    Platform.SWITCH,
    Platform.DATETIME,
    Platform.TODO,
]

# (resource_id, filename) — registered as Lovelace module resources
_FRONTEND_RESOURCES: list[tuple[str, str]] = [
    ("familyboard_event_themes", "event-themes.js"),
    ("familyboard_card", "familyboard-chores-card.js"),
    ("familyboard_filter_card", "familyboard-filter-card.js"),
    ("familyboard_view_card", "familyboard-view-card.js"),
    ("familyboard_category_card", "familyboard-category-card.js"),
    ("familyboard_calendar_card", "familyboard-calendar-card.js"),
    ("familyboard_progress_card", "familyboard-progress-card.js"),
    ("familyboard_countdown_card", "familyboard-countdown-card.js"),
    ("familyboard_recent_chores_card", "familyboard-recent-chores-card.js"),
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
ADD_MEAL_SCHEMA = vol.Schema({})
SNOOZE_TEST_SCHEMA = vol.Schema({vol.Required("uid"): cv.string})
CANCEL_REMINDER_SCHEMA = vol.Schema({vol.Required("uid"): cv.string})
SUGGEST_MEAL_SCHEMA = vol.Schema(
    {vol.Optional("date"): cv.date, vol.Optional("ai_task_entity"): cv.entity_id}
)
ACCEPT_MEAL_SUGGESTION_SCHEMA = vol.Schema({})
CLEAR_MEAL_SUGGESTION_SCHEMA = vol.Schema({})
CLAIM_CHORE_SCHEMA = vol.Schema(
    {
        vol.Required("uid"): cv.string,
        vol.Optional("member"): vol.Any(cv.string, None),
    }
)


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
    """Reload the integration when options or subentries change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate a v1 entry (list-shaped options) into v2 subentries.

    For each member / extra calendar / shared calendar / shared chore /
    trash sensor / meal planner / day override in the legacy options
    dict we synthesize a matching subentry with a stable ``unique_id``.
    The migration is idempotent: subentries with a matching
    ``(subentry_type, unique_id)`` are left alone, so re-running is
    safe. After migration the legacy lists are stripped from
    ``entry.options`` so subentries become the single source of truth.
    """
    if entry.version >= CONFIG_ENTRY_VERSION:
        return True

    options = dict(entry.options or {})
    created = await migrate_options_to_subentries(hass, entry, options)
    _LOGGER.info(
        "FamilyBoard: migrated entry %s to v%d (%d subentries created)",
        entry.entry_id,
        CONFIG_ENTRY_VERSION,
        created,
    )

    # Clear legacy list-shaped options so compose_conf is the only source.
    cleaned = {
        k: v
        for k, v in options.items()
        if k
        not in {
            "members",
            "trash",
            "shared_calendars",
            "shared_chores",
            "meal_calendar",
            "meal_planner",
        }
    }
    hass.config_entries.async_update_entry(
        entry, options=cleaned, version=CONFIG_ENTRY_VERSION
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up FamilyBoard from a config entry."""
    fb = hass.data.setdefault(DOMAIN, {})

    # If async_step_import created this entry just now, upsert the YAML
    # block into subentries before composing conf.
    pending_yaml = fb.pop("pending_yaml_import", None)
    if pending_yaml:
        from .subentries import upsert_yaml as _upsert_yaml

        await _upsert_yaml(hass, entry, pending_yaml)

    # v2: rebuild conf from subentries. Fall back to legacy options /
    # YAML for the brief window after install before any subentry
    # exists (e.g. user just clicked "Add integration" but hasn't added
    # a member yet).
    conf = compose_conf(entry)
    if not conf.get("members") and not entry.subentries:
        legacy = dict(entry.options) if entry.options else None
        conf = legacy or fb.get("yaml_config") or default_options()

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

    # CalDAV client managers (one per CalDAV connection subentry)
    caldav_managers: list[CalDAVClientManager] = []
    for caldav_conf in conf.get("caldav_connections", []):
        mgr = CalDAVClientManager(hass, caldav_conf)
        caldav_managers.append(mgr)
    fb["caldav_managers"] = caldav_managers

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
        for caldav_mgr in caldav_managers:
            try:
                await caldav_mgr.async_start()
            except Exception:
                _LOGGER.exception("CalDAV manager failed to start")
        await coordinator.async_load_meal_suggestion()
        await coordinator.async_load_claims()
        await coordinator.async_load_history()
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

    for caldav_mgr in fb.get("caldav_managers", []):
        await caldav_mgr.async_stop()

    for svc in ("add_event", "add_meal", "snooze_test", "cancel_reminder"):
        if hass.services.has_service(DOMAIN, svc):
            hass.services.async_remove(DOMAIN, svc)

    # Keep `config` so a YAML reload can re-create the entry without reload of HA
    fb.pop("reminder_manager", None)
    fb.pop("trash_chore_manager", None)
    fb.pop("caldav_managers", None)
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
    """Return ``<manifest-version>-<short-hash>`` for cache busting.

    The manifest version is exposed to cards via ``import.meta.url``'s ``?v=``
    query parameter so each card can print its actual version in console.info
    without a build step.
    """
    js_path = Path(__file__).parent / "frontend" / filename
    try:
        content = js_path.read_bytes()
    except OSError as err:
        _LOGGER.debug("Could not read %s for versioning: %s", js_path, err)
        return _get_manifest_version()
    short = hashlib.sha256(content).hexdigest()[:8]
    return f"{_get_manifest_version()}-{short}"


def _get_manifest_version() -> str:
    """Return the integration version from manifest.json (cached)."""
    cached = getattr(_get_manifest_version, "_cached", None)
    if cached:
        return cached
    manifest_path = Path(__file__).parent / "manifest.json"
    try:
        import json

        version = json.loads(manifest_path.read_text(encoding="utf-8")).get(
            "version", "0.0.0"
        )
    except (OSError, ValueError) as err:
        _LOGGER.debug("Could not read manifest version: %s", err)
        version = "0.0.0"
    _get_manifest_version._cached = version  # type: ignore[attr-defined]
    return version


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
    """Warn if required HACS frontend deps (mushroom, card-mod, bubble) are missing."""
    required = {
        "mushroom": "Mushroom Cards",
        "card-mod": "card-mod",
        "bubble-card": "Bubble Card",
    }
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

    async def handle_add_meal(call: ServiceCall) -> None:
        """Create an all-day meal event from the title + day_start entities.

        Reads ``text.familyboard_event_title`` (title) and
        ``datetime.familyboard_day_start`` (date) and writes an all-day
        event into the configured ``meal_calendar``. Resets the title
        afterwards. No service data required at the call site, so it can be
        triggered from a Mushroom chip / Bubble button without touching
        Jinja-in-data limitations.
        """
        meal_calendar = conf.get("meal_calendar")
        if not meal_calendar:
            raise HomeAssistantError(
                "meal_calendar is not configured in FamilyBoard options"
            )

        title = hass.states.get(EVENT_TITLE_ENTITY)
        day_start = hass.states.get(DAY_START_ENTITY)
        if not title or not day_start:
            raise HomeAssistantError("Missing entity states for add_meal")

        event_title = title.state
        if not event_title or event_title in ("unknown", "unavailable"):
            _LOGGER.debug("Empty meal title; skipping add_meal")
            return

        try:
            start_date = _dt.fromisoformat(day_start.state).date()
        except (ValueError, TypeError) as err:
            raise HomeAssistantError(
                f"Invalid day_start datetime: {day_start.state}"
            ) from err

        end_date = start_date + timedelta(days=1)

        await hass.services.async_call(
            "calendar",
            "create_event",
            {
                "summary": event_title,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
            target={"entity_id": meal_calendar},
            blocking=True,
        )

        await hass.services.async_call(
            "text",
            "set_value",
            {"entity_id": EVENT_TITLE_ENTITY, "value": ""},
            blocking=True,
        )

        # Refresh the meals sensor immediately so the dashboard reflects
        # the new event without waiting for the 5-minute coordinator tick.
        coordinator = hass.data.get(DOMAIN, {}).get("coordinator")
        if coordinator is not None:
            await coordinator.async_request_refresh()

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

    async def handle_suggest_meal(call: ServiceCall) -> None:
        """Generate a meal suggestion via ``ai_task.generate_data``.

        Uses the ``meal_planner`` options block for prompt configuration.
        ``date`` defaults to today; ``ai_task_entity`` overrides the
        configured one (one-shot, not persisted). Result is stored on the
        coordinator and exposed via ``sensor.familyboard_meal_suggestion``.
        """
        planner = hass.data[DOMAIN]["config"].get("meal_planner") or {}
        ai_entity = call.data.get("ai_task_entity") or planner.get("ai_task_entity")
        if not ai_entity:
            raise HomeAssistantError(
                "Maaltijdplanner is niet geconfigureerd. Stel een AI-task "
                "entiteit in via Instellingen \u2192 Apparaten \u2192 "
                "FamilyBoard \u2192 Configureren \u2192 Maaltijdplanner (AI)."
            )
        if hass.states.get(ai_entity) is None:
            raise HomeAssistantError(
                f"AI-task entiteit '{ai_entity}' bestaat niet. Controleer "
                "Instellingen \u2192 Apparaten \u2192 FamilyBoard \u2192 "
                "Configureren \u2192 Maaltijdplanner (AI)."
            )
        target_date = call.data.get("date") or dt_util.now().date()

        recent_items: list[dict] = []
        week: list[dict] = []
        coordinator: FamilyBoardCoordinator | None = hass.data.get(DOMAIN, {}).get(
            "coordinator"
        )
        if coordinator and coordinator.data:
            recent_items = list(coordinator.data.get("recent_meals") or [])
            meals_by_date: dict[str, dict] = {}
            for meal in coordinator.data.get("meals") or []:
                meals_by_date.setdefault(meal["date"], meal)
            today = dt_util.now().date()
            for offset in range(MEAL_LOOKAHEAD_DAYS):
                day = today + timedelta(days=offset)
                iso = day.isoformat()
                week.append(
                    {
                        "date": iso,
                        "weekday": day.strftime("%A"),
                        "meal": meals_by_date.get(iso),
                    }
                )

        prompt = build_meal_prompt(
            target_date,
            planner=planner,
            recent_items=recent_items,
            week=week,
        )

        result = await hass.services.async_call(
            "ai_task",
            "generate_data",
            {
                "task_name": "FamilyBoard meal suggestion",
                "entity_id": ai_entity,
                "instructions": prompt,
                "structure": {
                    "title": {
                        "description": "Naam van de maaltijd, max 4 woorden",
                        "required": True,
                        "selector": {"text": {}},
                    },
                    "reason": {
                        "description": (
                            "Korte reden (1 zin) waarom dit een goede keuze is"
                        ),
                        "required": True,
                        "selector": {"text": {}},
                    },
                    "ingredients": {
                        "description": (
                            "Boodschappen, alleen losse strings, geen hoeveelheden"
                        ),
                        "required": True,
                        "selector": {"text": {"multiple": True}},
                    },
                },
            },
            blocking=True,
            return_response=True,
        )

        data = (result or {}).get("data") if isinstance(result, dict) else None
        if not isinstance(data, dict):
            raise HomeAssistantError(
                f"ai_task.generate_data returned unexpected payload: {result!r}"
            )

        suggestion = {
            "date": target_date.isoformat(),
            "title": str(data.get("title") or "").strip(),
            "reason": str(data.get("reason") or "").strip(),
            "ingredients": [
                str(i).strip()
                for i in (data.get("ingredients") or [])
                if str(i).strip()
            ],
            "generated_at": dt_util.utcnow().isoformat(),
        }
        if coordinator is not None:
            await coordinator.async_set_meal_suggestion(suggestion)

    async def handle_accept_meal_suggestion(call: ServiceCall) -> None:
        """Apply the stored suggestion: create meal event + shopping items."""
        coordinator: FamilyBoardCoordinator | None = hass.data.get(DOMAIN, {}).get(
            "coordinator"
        )
        suggestion = coordinator.meal_suggestion if coordinator else None
        if not suggestion or not suggestion.get("title"):
            raise HomeAssistantError(
                "Geen actieve maaltijdsuggestie. Tik eerst op Vandaag, "
                "Morgen of Overmorgen om er een te genereren."
            )

        meal_calendar = hass.data[DOMAIN]["config"].get("meal_calendar")
        if not meal_calendar:
            raise HomeAssistantError(
                "meal_calendar is niet geconfigureerd. Stel deze in via "
                "FamilyBoard \u2192 Configureren \u2192 Algemene instellingen."
            )

        try:
            target = _dt.fromisoformat(suggestion["date"]).date()
        except (KeyError, ValueError) as err:
            raise HomeAssistantError(f"Invalid suggestion date: {err}") from err

        await hass.services.async_call(
            "calendar",
            "create_event",
            {
                "summary": suggestion["title"],
                "start_date": target.isoformat(),
                "end_date": (target + timedelta(days=1)).isoformat(),
            },
            target={"entity_id": meal_calendar},
            blocking=True,
        )

        planner = hass.data[DOMAIN]["config"].get("meal_planner") or {}
        shopping_list = planner.get("shopping_list")
        if shopping_list:
            for item in suggestion.get("ingredients", []):
                await hass.services.async_call(
                    "todo",
                    "add_item",
                    {"item": item},
                    target={"entity_id": shopping_list},
                    blocking=True,
                )

        if coordinator is not None:
            await coordinator.async_set_meal_suggestion(None)
            await coordinator.async_request_refresh()

    async def handle_clear_meal_suggestion(call: ServiceCall) -> None:
        """Discard the current meal suggestion without acting on it."""
        coordinator: FamilyBoardCoordinator | None = hass.data.get(DOMAIN, {}).get(
            "coordinator"
        )
        if coordinator is not None:
            await coordinator.async_set_meal_suggestion(None)

    async def handle_claim_chore(call: ServiceCall) -> None:
        """Claim a shared chore for a member, or release with member=None."""
        coordinator: FamilyBoardCoordinator | None = hass.data.get(DOMAIN, {}).get(
            "coordinator"
        )
        if coordinator is None:
            raise HomeAssistantError("FamilyBoard coordinator is not running")
        uid = call.data["uid"]
        member = call.data.get("member")
        await coordinator.async_set_claim(uid, member)

    hass.services.async_register(
        DOMAIN, "add_event", handle_add_event, schema=ADD_EVENT_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "add_meal", handle_add_meal, schema=ADD_MEAL_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "snooze_test", handle_snooze_test, schema=SNOOZE_TEST_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "cancel_reminder", handle_cancel_reminder, schema=CANCEL_REMINDER_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "suggest_meal", handle_suggest_meal, schema=SUGGEST_MEAL_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        "accept_meal_suggestion",
        handle_accept_meal_suggestion,
        schema=ACCEPT_MEAL_SUGGESTION_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        "clear_meal_suggestion",
        handle_clear_meal_suggestion,
        schema=CLEAR_MEAL_SUGGESTION_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        "claim_chore",
        handle_claim_chore,
        schema=CLAIM_CHORE_SCHEMA,
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
        # One-shot warning de-duplication (Phase 1 chore-filter fixes).
        self._warned_unknown_shared_member: set[tuple[str, str]] = set()
        self._warn_chore_entity_overlap()
        self._meal_suggestion_store: Store = Store(
            hass, MEAL_SUGGESTION_STORAGE_VERSION, MEAL_SUGGESTION_STORAGE_KEY
        )
        self._meal_suggestion: dict | None = None
        # Phase 4: shared-chore claim store. Maps todo UID → member name.
        # Unclaimed shared chores credit nobody on completion; claimed
        # ones credit only the claimer.
        self._claim_store: Store = Store(
            hass, CHORE_CLAIM_STORAGE_VERSION, CHORE_CLAIM_STORAGE_KEY
        )
        self._claims: dict[str, str] = {}
        self._claims_loaded: bool = False
        # Phase 5: chore-completion history. Per-member monotonic
        # counters (so HA recorder/statistics can produce hourly /
        # daily / weekly aggregates — the energy-dashboard pattern)
        # plus a bounded recent-log for the recent-completions card.
        self._history_store: Store = Store(
            hass, CHORE_HISTORY_STORAGE_VERSION, CHORE_HISTORY_STORAGE_KEY
        )
        self._completion_totals: dict[str, int] = {}
        self._recent_completions: list[dict] = []
        self._history_loaded: bool = False
        # Snapshot of last tick's chores keyed by uid — lets us look
        # up summary/owner/source when a uid disappears between ticks.
        self._prev_chore_meta: dict[str, dict] = {}

    async def async_load_claims(self) -> None:
        """Load shared-chore claims from disk (call once at setup)."""
        data = await self._claim_store.async_load()
        if isinstance(data, dict):
            # Filter to known member names so a removed member's stale
            # claims don't silently hide a chore from everyone.
            known = {m["name"] for m in self.members}
            self._claims = {
                uid: member
                for uid, member in data.items()
                if isinstance(uid, str) and isinstance(member, str) and member in known
            }
        self._claims_loaded = True

    async def async_set_claim(self, uid: str, member: str | None) -> None:
        """Set or release a claim for a shared chore UID.

        ``member=None`` releases an existing claim. Triggers a
        coordinator refresh so cards update immediately.
        """
        if not self._claims_loaded:
            await self.async_load_claims()
        if member is None:
            self._claims.pop(uid, None)
        else:
            known = {m["name"] for m in self.members}
            if member not in known:
                raise HomeAssistantError(
                    f"FamilyBoard: cannot claim for unknown member {member!r}. "
                    f"Known: {sorted(known)}"
                )
            self._claims[uid] = member
        await self._claim_store.async_save(dict(self._claims))
        await self.async_request_refresh()

    @property
    def claims(self) -> dict[str, str]:
        """Return a snapshot of the current `{uid: member}` claim map."""
        return dict(self._claims)

    async def async_load_history(self) -> None:
        """Load chore-completion history from disk (call once at setup).

        Storage shape::

            {
              "completion_totals": {"Berry": 12, "Sylvia": 7, ...},
              "recent": [
                {"ts": "2026-05-09T18:32:00+02:00",
                 "member": "Berry" | None,
                 "summary": "Trash",
                 "uid": "abc123",
                 "source": "personal|shared",
                 "todo_entity": "todo.trash"},
                ...
              ]
            }

        Members no longer in config are dropped from totals so a
        removed member doesn't haunt the dashboard.
        """
        data = await self._history_store.async_load()
        known = {m["name"] for m in self.members}
        if isinstance(data, dict):
            totals = data.get("completion_totals") or {}
            self._completion_totals = {
                str(k): int(v)
                for k, v in totals.items()
                if isinstance(v, (int, float)) and k in known
            }
            recent = data.get("recent") or []
            if isinstance(recent, list):
                self._recent_completions = [
                    e
                    for e in recent
                    if isinstance(e, dict) and e.get("ts") and e.get("summary")
                ]
            self._prune_recent_log()
        for name in known:
            self._completion_totals.setdefault(name, 0)
        self._history_loaded = True

    def _prune_recent_log(self) -> None:
        """Trim the recent log to the configured count + age caps."""
        if not self._recent_completions:
            return
        cutoff = dt_util.now() - timedelta(days=CHORE_HISTORY_MAX_DAYS)
        kept: list[dict] = []
        for entry in self._recent_completions:
            try:
                ts = dt_util.parse_datetime(entry["ts"])
            except (TypeError, ValueError):
                continue
            if ts and ts >= cutoff:
                kept.append(entry)
        # Newest first, then cap to MAX_ENTRIES.
        kept.sort(key=lambda e: e["ts"], reverse=True)
        self._recent_completions = kept[:CHORE_HISTORY_MAX_ENTRIES]

    async def _record_completion(
        self,
        *,
        uid: str,
        member: str | None,
        summary: str,
        todo_entity: str,
        source: str,
    ) -> None:
        """Append a completion to the history log and bump counters.

        ``member=None`` records the completion for the recent-list
        sensor without crediting any per-member counter — used for
        unclaimed shared chores (Option A semantics).
        """
        if not self._history_loaded:
            return
        entry = {
            "ts": dt_util.now().isoformat(),
            "member": member,
            "summary": summary,
            "uid": uid,
            "source": source,
            "todo_entity": todo_entity,
        }
        self._recent_completions.insert(0, entry)
        self._prune_recent_log()
        if member is not None:
            self._completion_totals[member] = self._completion_totals.get(member, 0) + 1

    async def _persist_history(self) -> None:
        """Write counters + recent-log snapshot to disk."""
        await self._history_store.async_save(
            {
                "completion_totals": dict(self._completion_totals),
                "recent": list(self._recent_completions),
            }
        )

    @property
    def completion_totals(self) -> dict[str, int]:
        """Return per-member cumulative completion counts."""
        return dict(self._completion_totals)

    @property
    def recent_completions(self) -> list[dict]:
        """Return the bounded recent-completions log (newest first)."""
        return list(self._recent_completions)

    async def async_load_meal_suggestion(self) -> None:
        """Load the persisted meal suggestion from disk (call before refresh)."""
        data = await self._meal_suggestion_store.async_load()
        if isinstance(data, dict) and data.get("title"):
            self._meal_suggestion = data

    async def async_set_meal_suggestion(self, suggestion: dict | None) -> None:
        """Persist a new (or cleared) meal suggestion and refresh listeners."""
        self._meal_suggestion = suggestion
        await self._meal_suggestion_store.async_save(suggestion or {})
        await self.async_request_refresh()

    @property
    def meal_suggestion(self) -> dict | None:
        """Return the current persisted meal suggestion, if any."""
        return self._meal_suggestion

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
        if view == "today":
            return (today.isoformat(), today.isoformat())
        if view == "2_days":
            return (today.isoformat(), (today + timedelta(days=1)).isoformat())
        if view == "3_days":
            return (today.isoformat(), (today + timedelta(days=2)).isoformat())
        if view == "week":
            return (today.isoformat(), (today + timedelta(days=7)).isoformat())
        if view == "work_week":
            # Mon..Fri. On Sat/Sun, target the upcoming work week so
            # "Werkweek" never collapses to a fully-past window.
            weekday = today.weekday()  # Mon=0 .. Sun=6
            if weekday >= 5:  # Sat/Sun → jump to next Monday
                monday = today + timedelta(days=7 - weekday)
            else:
                monday = today - timedelta(days=weekday)
            friday = monday + timedelta(days=4)
            return (monday.isoformat(), friday.isoformat())
        if view == "two_weeks":
            return (today.isoformat(), (today + timedelta(days=14)).isoformat())
        if view == "month":
            return (today.isoformat(), (today + timedelta(days=30)).isoformat())
        return None

    def _chore_in_view(self, chore: dict, view_window: tuple[str, str] | None) -> bool:
        """Return True if the chore's due date falls inside the view window."""
        if view_window is None:
            return True
        due = chore.get("due")
        if not due:
            return True
        # `due` may be a date ("YYYY-MM-DD") or a full ISO datetime
        # ("YYYY-MM-DDTHH:MM:SS+TZ"; CalDAV/Nextcloud returns the latter
        # when a VTODO carries a time-of-day). Compare on the date prefix
        # only — the view window is date-granular.
        due_date = due[:10]
        if due_date < view_window[0]:
            return True
        return view_window[0] <= due_date <= view_window[1]

    @staticmethod
    def _chore_due_today_or_overdue(chore: dict, today_str: str) -> bool:
        """Return True if the chore is due today, overdue, or has no due date."""
        due = chore.get("due")
        if not due:
            return True
        return due[:10] <= today_str

    def _warn_chore_entity_overlap(self) -> None:
        """Warn once when a `todo.*` entity is listed both personal and shared.

        A shared entry that also appears in a member's personal ``chores``
        list is silently shadowed by the personal copy in the fan-out loop
        (the personal copy lacks the ``shared`` flag, so it never reaches
        the shared-mode card). This is a config smell — warn but do not
        auto-correct.
        """
        personal_owners: dict[str, list[str]] = {}
        for member in self.members:
            for ent in member.get("chores", []) or []:
                personal_owners.setdefault(ent, []).append(member["name"])
        for shared in self.conf.get("shared_chores", []) or []:
            ent = shared.get("entity")
            if ent and ent in personal_owners:
                _LOGGER.warning(
                    "FamilyBoard: todo entity %s is listed as a shared chore "
                    "and also appears in personal chores for %s. The personal "
                    "copy will shadow the shared one and items may not appear "
                    "on the shared (algemene) card. Remove %s from the "
                    "personal chores list to fix.",
                    ent,
                    ", ".join(personal_owners[ent]),
                    ent,
                )

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
            "claims": dict(self._claims),
            "completion_totals": dict(self._completion_totals),
            "recent_completions": list(self._recent_completions),
            "progress": {},
            "display": dict(self.conf.get("display", {})),
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

        # Shared chores: fan out to each listed member. Honor the claim
        # store — a claimed shared chore goes only to the claimer; an
        # unclaimed one fans out as before.
        seen_shared_uids: set[str] = set()
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
                uid = todo_item.get("uid")
                if uid:
                    seen_shared_uids.add(uid)
                claimed_by = self._claims.get(uid) if uid else None
                if claimed_by and claimed_by not in result["member_chores"]:
                    # Stale claim for a member that no longer exists —
                    # ignore and treat as unclaimed for this tick.
                    claimed_by = None
                # When claimed, only the claimer sees it. When unclaimed,
                # every listed member sees it (existing behavior).
                target_members = [claimed_by] if claimed_by else list(shared_members)
                for mname in target_members:
                    if mname not in result["member_chores"]:
                        warn_key = (shared_entity, mname)
                        if warn_key not in self._warned_unknown_shared_member:
                            self._warned_unknown_shared_member.add(warn_key)
                            _LOGGER.warning(
                                "FamilyBoard: shared chore %s lists member "
                                "%r which is not configured. Items will not "
                                "appear on that member's card. Configured "
                                "members: %s",
                                shared_entity,
                                mname,
                                ", ".join(result["member_chores"].keys()) or "(none)",
                            )
                        continue
                    meta = member_meta.get(mname, {})
                    existing_uids = {
                        c.get("uid")
                        for c in result["member_chores"][mname]
                        if c.get("uid")
                    }
                    if uid and uid in existing_uids:
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
                            "uid": uid,
                            "completed": False,
                            "shared": True,
                            "shared_members": shared_members,
                            "shared_name": shared_name,
                            "shared_color": shared_color,
                            "claimed_by": claimed_by,
                        }
                    )

        # Prune claims whose underlying UID no longer exists in any
        # shared todo list (chore deleted or completed). Keep storage
        # honest so the in-memory map and disk stay bounded.
        if self._claims_loaded and self._claims:
            stale = [uid for uid in self._claims if uid not in seen_shared_uids]
            if stale:
                for uid in stale:
                    self._claims.pop(uid, None)
                await self._claim_store.async_save(dict(self._claims))

        # Combine + dedup + filter by view window. Shared chores bypass the
        # view-window trim so the algemene card always surfaces them, even
        # when `select.familyboard_view` is narrowed to today.
        all_chores: list[dict] = []
        for chores_list in result["member_chores"].values():
            for chore in chores_list:
                if chore.get("shared") or self._chore_in_view(chore, view_window):
                    all_chores.append(chore)

        # Dedup shared chores by UID when present, else by
        # (entity, summary, due) so todo backends that omit UIDs still
        # produce one row per shared item rather than N copies.
        seen_shared_keys: set[tuple] = set()
        deduped_chores: list[dict] = []
        for chore in all_chores:
            if chore.get("shared"):
                uid = chore.get("uid")
                key = (
                    ("uid", uid)
                    if uid
                    else (
                        "fallback",
                        chore.get("todo_entity"),
                        chore.get("summary"),
                        chore.get("due"),
                    )
                )
                if key in seen_shared_keys:
                    continue
                seen_shared_keys.add(key)
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

        # Phase 5: per-uid snapshot used to detect completions across
        # ticks regardless of credit attribution. Covers personal,
        # claimed-shared and unclaimed-shared chores. We pick the
        # first occurrence of each uid (claimed shared chores only
        # appear once anyway; unclaimed shared chores appear N times
        # via fan-out — credit_member ends up as None either way).
        current_chore_meta: dict[str, dict] = {}
        for chore in deduped_chores:
            uid = chore.get("uid")
            if not uid:
                continue
            if chore.get("shared"):
                credit_member = chore.get("claimed_by")  # None when unclaimed
                source = "shared"
            else:
                credit_member = chore.get("member")
                source = "personal"
            current_chore_meta.setdefault(
                uid,
                {
                    "summary": chore.get("summary", ""),
                    "todo_entity": chore.get("todo_entity", ""),
                    "credit_member": credit_member,
                    "source": source,
                },
            )

        if self._history_loaded and self._prev_chore_meta:
            disappeared_uids = set(self._prev_chore_meta) - set(current_chore_meta)
            recorded_any = False
            for uid in disappeared_uids:
                prev = self._prev_chore_meta[uid]
                await self._record_completion(
                    uid=uid,
                    member=prev.get("credit_member"),
                    summary=prev.get("summary", ""),
                    todo_entity=prev.get("todo_entity", ""),
                    source=prev.get("source", "personal"),
                )
                recorded_any = True
            if recorded_any:
                await self._persist_history()
        self._prev_chore_meta = current_chore_meta

        # Daily-progress tracking — derive completed counts from the
        # persisted history log so they survive HA restarts.
        today_date = now.date()
        completed_today: dict[str, int] = {}
        for entry in self._recent_completions:
            member = entry.get("member")
            if not member:
                continue
            ts = dt_util.parse_datetime(entry.get("ts") or "")
            if ts and ts.date() == today_date:
                completed_today[member] = completed_today.get(member, 0) + 1
            elif ts and ts.date() < today_date:
                break  # entries are newest-first; no more today entries

        for member in self.members:
            mname = member["name"]
            completed = completed_today.get(mname, 0)
            active = len(
                [
                    c
                    for c in result["member_chores"].get(mname, [])
                    if self._chore_due_today_or_overdue(c, today_str)
                    and (not c.get("shared") or c.get("claimed_by") == mname)
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

        # Refresh history snapshots (they may have been mutated by
        # _record_completion / _persist_history above).
        result["completion_totals"] = dict(self._completion_totals)
        result["recent_completions"] = list(self._recent_completions)

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
        result["recent_meals"] = await self._fetch_recent_meals(now)
        result["meal_suggestion"] = self._meal_suggestion

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
            title = ev.get("summary", "")
            meals.append(
                {
                    "date": date,
                    "title": title,
                    "start": start,
                    "end": end,
                    "description": ev.get("description", ""),
                    "uid": ev.get("uid", ""),
                    "all_day": "T" not in start,
                    "status": "skipped" if is_meal_placeholder(title) else "planned",
                }
            )
        meals.sort(key=lambda m: m["start"])
        return meals

    async def _fetch_recent_meals(self, now: _dt) -> list[dict]:
        """Fetch and score recently-used meal titles for the picker.

        Window: ``MEAL_RECENT_WINDOW_DAYS`` back through today. Returns the
        top results from :func:`score_recent_meals`.
        """
        meal_entity = self.conf.get("meal_calendar")
        if not meal_entity:
            return []

        today = now.date()
        window_start = _dt.combine(
            today - timedelta(days=MEAL_RECENT_WINDOW_DAYS),
            time.min,
            tzinfo=now.tzinfo,
        )
        window_end = _dt.combine(today, time.max, tzinfo=now.tzinfo)
        events = await self._fetch_events(
            meal_entity, window_start.isoformat(), window_end.isoformat()
        )

        normalised: list[dict] = []
        for ev in events:
            start = ev.get("start") or ""
            date = start[:10]
            if not date:
                continue
            normalised.append({"title": ev.get("summary", ""), "date": date})
        return score_recent_meals(normalised, today)
