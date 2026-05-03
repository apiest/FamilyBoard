"""Subentry handling for FamilyBoard.

Each user-managed list (members, extra calendars, shared calendars,
shared chores, trash sensors, meal planner, meal day-overrides) is
exposed as its own HA *subentry* under the integration page. This
module owns:

* Subtype-stable identity helpers (``_member_uid`` …).
* ``compose_conf(entry)`` which walks ``entry.subentries`` and rebuilds
  the legacy ``conf`` dict the rest of the integration consumes
  (``members``, ``trash``, ``shared_calendars``, ``shared_chores``,
  ``meal_calendar``, ``meal_planner``).
* ``migrate_options_to_subentries(hass, entry, options)`` which turns
  a v1 ``entry.options`` dict into v2 subentries (idempotent).
* ``upsert_yaml(hass, entry, yaml_conf)`` which performs the YAML
  import as add-or-update by ``unique_id``. UI-only subentries (no
  YAML twin) are left untouched.
* The seven ``ConfigSubentryFlow`` classes that drive the add /
  reconfigure dialogs.

Keeping this in its own module keeps ``config_flow.py`` slim and makes
the migration path easy to test in isolation.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from homeassistant import config_entries
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigSubentry,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
import voluptuous as vol

from .const import (
    CALENDAR_CATEGORIES,
    DEFAULT_CALENDAR_CATEGORY,
    SUBENTRY_EXTRA_CALENDAR,
    SUBENTRY_MEAL_DAY_OVERRIDE,
    SUBENTRY_MEAL_PLANNER,
    SUBENTRY_MEMBER,
    SUBENTRY_SHARED_CALENDAR,
    SUBENTRY_SHARED_CHORE,
    SUBENTRY_TRASH,
    WEEKDAYS,
)

# ---------------------------------------------------------------------------
# Identity helpers (stable unique_ids for upsert)
# ---------------------------------------------------------------------------


def _slug(value: str) -> str:
    """Lowercase + collapse non-word characters for unique_id stability."""
    return re.sub(r"\W+", "_", (value or "").strip().lower()).strip("_")


def member_uid(name: str) -> str:
    """Return the stable unique_id for a member subentry."""
    return _slug(name)


def extra_calendar_uid(member_name: str, label_or_entity: str) -> str:
    """Return the stable unique_id for an extra-calendar subentry."""
    return f"{_slug(member_name)}__{_slug(label_or_entity)}"


def shared_calendar_uid(entity: str) -> str:
    """Return the stable unique_id for a shared-calendar subentry."""
    return entity


def shared_chore_uid(entity: str) -> str:
    """Return the stable unique_id for a shared-chore subentry."""
    return entity


def trash_uid(trash_type: str) -> str:
    """Return the stable unique_id for a trash subentry."""
    return _slug(trash_type)


def meal_planner_uid() -> str:
    """Return the stable unique_id for the singleton meal-planner subentry."""
    return "default"


def meal_day_override_uid(weekday: str) -> str:
    """Return the stable unique_id for a meal day-override subentry."""
    return weekday.lower()


# ---------------------------------------------------------------------------
# compose_conf — rebuild legacy ``conf`` dict from subentries
# ---------------------------------------------------------------------------


def compose_conf(entry: ConfigEntry) -> dict[str, Any]:
    """Walk ``entry.subentries`` and return the legacy normalized config.

    The shape is identical to what ``OPTIONS_SCHEMA`` produces, so the
    coordinator, calendar / sensor / select platforms and trash chore
    manager don't need to change.
    """
    members_by_name: dict[str, dict[str, Any]] = {}
    extras_by_member: dict[str, list[dict[str, Any]]] = {}
    trash: list[dict[str, Any]] = []
    shared_calendars: list[dict[str, Any]] = []
    shared_chores: list[dict[str, Any]] = []
    meal_planner: dict[str, Any] | None = None
    meal_overrides: dict[str, dict[str, Any]] = {}
    meal_calendar: str | None = None

    for sub in entry.subentries.values():
        data = dict(sub.data)
        st = sub.subentry_type
        if st == SUBENTRY_MEMBER:
            name = data.get("name")
            if not name:
                continue
            data.setdefault("extra_calendars", [])
            data.setdefault("chores", [])
            members_by_name[name] = data
        elif st == SUBENTRY_EXTRA_CALENDAR:
            parent = data.pop("parent_member", None)
            if not parent:
                continue
            extras_by_member.setdefault(parent, []).append(data)
        elif st == SUBENTRY_SHARED_CALENDAR:
            shared_calendars.append(data)
        elif st == SUBENTRY_SHARED_CHORE:
            shared_chores.append(data)
        elif st == SUBENTRY_TRASH:
            trash.append(data)
        elif st == SUBENTRY_MEAL_PLANNER:
            meal_planner = {k: v for k, v in data.items() if k != "meal_calendar"}
            meal_calendar = data.get("meal_calendar") or meal_calendar
        elif st == SUBENTRY_MEAL_DAY_OVERRIDE:
            wd = data.get("weekday")
            if wd:
                ov = {k: v for k, v in data.items() if k != "weekday"}
                meal_overrides[wd] = ov

    # Attach extras to members
    for name, extras in extras_by_member.items():
        if name in members_by_name:
            members_by_name[name]["extra_calendars"].extend(extras)

    if meal_planner is not None and meal_overrides:
        meal_planner.setdefault("day_overrides", {}).update(meal_overrides)

    conf: dict[str, Any] = {
        "members": list(members_by_name.values()),
        "trash": trash,
        "shared_calendars": shared_calendars,
        "shared_chores": shared_chores,
    }
    if meal_calendar:
        conf["meal_calendar"] = meal_calendar
    if meal_planner is not None:
        conf["meal_planner"] = meal_planner
    return conf


# ---------------------------------------------------------------------------
# Migration: legacy ``entry.options`` → subentries (one-shot, idempotent)
# ---------------------------------------------------------------------------


async def migrate_options_to_subentries(
    hass: HomeAssistant, entry: ConfigEntry, options: dict[str, Any]
) -> int:
    """Synthesize subentries from a v1 options dict.

    Existing subentries with the same ``unique_id`` are skipped, so the
    function is safe to re-run. Returns the number of subentries
    created.
    """
    existing_uids: set[tuple[str, str | None]] = {
        (s.subentry_type, s.unique_id) for s in entry.subentries.values()
    }
    created = 0

    def _add(subtype: str, title: str, unique_id: str, data: dict[str, Any]) -> None:
        nonlocal created
        if (subtype, unique_id) in existing_uids:
            return
        sub = ConfigSubentry(
            subentry_type=subtype, title=title, unique_id=unique_id, data=data
        )
        hass.config_entries.async_add_subentry(entry, sub)
        existing_uids.add((subtype, unique_id))
        created += 1

    for member in options.get("members") or []:
        m = dict(member)
        extras = m.pop("extra_calendars", []) or []
        name = m.get("name")
        if not name:
            continue
        _add(SUBENTRY_MEMBER, name, member_uid(name), m)
        for ex in extras:
            ex_data = dict(ex)
            ex_data["parent_member"] = name
            label = ex.get("label") or ex.get("entity") or ""
            _add(
                SUBENTRY_EXTRA_CALENDAR,
                f"{name} · {label}",
                extra_calendar_uid(name, ex.get("entity", label)),
                ex_data,
            )

    for trash in options.get("trash") or []:
        t = dict(trash)
        # Legacy carve-out: pre-existing trash entries kept their
        # auto-chore behaviour (defaulted to True). New entries created
        # via the UI default to False.
        t.setdefault("reminder_bins", True)
        t.setdefault("reminder_kliko", True)
        ttype = t.get("type")
        if not ttype:
            continue
        title = t.get("label") or ttype
        _add(SUBENTRY_TRASH, title, trash_uid(ttype), t)

    for sc in options.get("shared_calendars") or []:
        sc_data = dict(sc)
        entity = sc.get("entity")
        if not entity:
            continue
        title = sc.get("name") or entity
        _add(SUBENTRY_SHARED_CALENDAR, title, shared_calendar_uid(entity), sc_data)

    for ch in options.get("shared_chores") or []:
        ch_data = dict(ch)
        entity = ch.get("entity")
        if not entity:
            continue
        title = ch.get("name") or entity
        _add(SUBENTRY_SHARED_CHORE, title, shared_chore_uid(entity), ch_data)

    planner = options.get("meal_planner")
    if planner:
        p_data = dict(planner)
        overrides = p_data.pop("day_overrides", {}) or {}
        if options.get("meal_calendar"):
            p_data["meal_calendar"] = options["meal_calendar"]
        _add(SUBENTRY_MEAL_PLANNER, "Meal planner", meal_planner_uid(), p_data)
        for weekday, ov in overrides.items():
            wd = weekday.lower()
            if wd not in WEEKDAYS:
                continue
            ov_data = dict(ov)
            ov_data["weekday"] = wd
            _add(
                SUBENTRY_MEAL_DAY_OVERRIDE,
                wd.capitalize(),
                meal_day_override_uid(wd),
                ov_data,
            )
    elif options.get("meal_calendar"):
        # meal_calendar without planner → still useful for the meals card.
        _add(
            SUBENTRY_MEAL_PLANNER,
            "Meal planner",
            meal_planner_uid(),
            {"meal_calendar": options["meal_calendar"]},
        )

    return created


# ---------------------------------------------------------------------------
# YAML upsert (called from ConfigFlow.async_step_import)
# ---------------------------------------------------------------------------


def _find_subentry(
    entry: ConfigEntry, subtype: str, unique_id: str
) -> ConfigSubentry | None:
    """Return the subentry matching (subtype, unique_id) or ``None``."""
    for sub in entry.subentries.values():
        if sub.subentry_type == subtype and sub.unique_id == unique_id:
            return sub
    return None


async def upsert_yaml(
    hass: HomeAssistant, entry: ConfigEntry, yaml_conf: dict[str, Any]
) -> None:
    """Add-or-update subentries from a YAML ``familyboard:`` block.

    Subentries the user added via the UI without a YAML twin are kept
    intact. Subentries that *were* in YAML but are no longer present
    are NOT auto-deleted (avoids accidental data loss); a warning is
    logged so the user can clean up via the UI.
    """

    def _upsert(subtype: str, title: str, unique_id: str, data: dict[str, Any]) -> None:
        existing = _find_subentry(entry, subtype, unique_id)
        if existing is None:
            sub = ConfigSubentry(
                subentry_type=subtype, title=title, unique_id=unique_id, data=data
            )
            hass.config_entries.async_add_subentry(entry, sub)
        else:
            hass.config_entries.async_update_subentry(
                entry, existing, data=data, title=title
            )

    for member in yaml_conf.get("members") or []:
        m = dict(member)
        extras = m.pop("extra_calendars", []) or []
        name = m.get("name")
        if not name:
            continue
        _upsert(SUBENTRY_MEMBER, name, member_uid(name), m)
        for ex in extras:
            ex_data = dict(ex)
            ex_data["parent_member"] = name
            label = ex.get("label") or ex.get("entity") or ""
            _upsert(
                SUBENTRY_EXTRA_CALENDAR,
                f"{name} · {label}",
                extra_calendar_uid(name, ex.get("entity", label)),
                ex_data,
            )

    for trash in yaml_conf.get("trash") or []:
        t = dict(trash)
        # YAML preserves legacy default-true reminder behavior when
        # the keys are absent.
        t.setdefault("reminder_bins", True)
        t.setdefault("reminder_kliko", True)
        ttype = t.get("type")
        if not ttype:
            continue
        _upsert(SUBENTRY_TRASH, t.get("label") or ttype, trash_uid(ttype), t)

    for sc in yaml_conf.get("shared_calendars") or []:
        sc_data = dict(sc)
        entity = sc.get("entity")
        if not entity:
            continue
        _upsert(
            SUBENTRY_SHARED_CALENDAR,
            sc.get("name") or entity,
            shared_calendar_uid(entity),
            sc_data,
        )

    for ch in yaml_conf.get("shared_chores") or []:
        ch_data = dict(ch)
        entity = ch.get("entity")
        if not entity:
            continue
        _upsert(
            SUBENTRY_SHARED_CHORE,
            ch.get("name") or entity,
            shared_chore_uid(entity),
            ch_data,
        )

    planner = yaml_conf.get("meal_planner")
    if planner or yaml_conf.get("meal_calendar"):
        p_data = dict(planner or {})
        overrides = p_data.pop("day_overrides", {}) or {}
        if yaml_conf.get("meal_calendar"):
            p_data["meal_calendar"] = yaml_conf["meal_calendar"]
        _upsert(SUBENTRY_MEAL_PLANNER, "Meal planner", meal_planner_uid(), p_data)
        for weekday, ov in overrides.items():
            wd = weekday.lower()
            if wd not in WEEKDAYS:
                continue
            ov_data = dict(ov)
            ov_data["weekday"] = wd
            _upsert(
                SUBENTRY_MEAL_DAY_OVERRIDE,
                wd.capitalize(),
                meal_day_override_uid(wd),
                ov_data,
            )


# ---------------------------------------------------------------------------
# Subentry flows
# ---------------------------------------------------------------------------


def _text_sel() -> selector.Selector:
    """Return a single-line text selector."""
    return selector.TextSelector(selector.TextSelectorConfig())


def _multiline_sel() -> selector.Selector:
    """Return a multi-line text selector."""
    return selector.TextSelector(selector.TextSelectorConfig(multiline=True))


def _entity_sel(domain: str, multiple: bool = False) -> selector.Selector:
    """Return an entity selector restricted to ``domain``."""
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain=domain, multiple=multiple)
    )


def _members_sel(member_names: list[str]) -> selector.Selector:
    """Return a multi-select dropdown of member names."""
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=member_names or ["(no members)"],
            multiple=True,
            mode=selector.SelectSelectorMode.LIST,
        )
    )


def _category_sel() -> selector.Selector:
    """Return a single-select dropdown of calendar categories."""
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=list(CALENDAR_CATEGORIES),
            mode=selector.SelectSelectorMode.DROPDOWN,
            translation_key="calendar_category",
        )
    )


def _strip_empties(data: dict[str, Any]) -> dict[str, Any]:
    """Drop keys whose value is None or an empty string/list."""
    out: dict[str, Any] = {}
    for k, v in data.items():
        if v is None:
            continue
        if isinstance(v, str) and v == "":
            continue
        if isinstance(v, list) and not v:
            continue
        out[k] = v
    return out


def _split_lines(value: str | None) -> list[str]:
    """Split a multi-line text field into a stripped non-empty list."""
    if not value:
        return []
    return [line.strip() for line in value.splitlines() if line.strip()]


# ----- Member ---------------------------------------------------------------


class MemberSubentryFlow(ConfigSubentryFlow):
    """Add or reconfigure a member subentry."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Show the form (handles both add and reconfigure submissions)."""
        existing = None
        if self.source == config_entries.SOURCE_RECONFIGURE:
            existing = dict(self._get_reconfigure_subentry().data)
        return await self._show(user_input, existing=existing)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Edit form pre-filled from the existing subentry data."""
        existing = self._get_reconfigure_subentry()
        return await self._show(user_input, existing=dict(existing.data))

    async def _show(
        self,
        user_input: dict[str, Any] | None,
        existing: dict[str, Any] | None,
    ) -> SubentryFlowResult:
        if user_input is not None:
            data = _strip_empties(user_input)
            data.setdefault("color", "#A8C8EC")
            data.setdefault("chores", data.get("chores") or [])
            name = data.get("name") or ""
            uid = member_uid(name)
            if existing is None:
                return self.async_create_entry(title=name, data=data, unique_id=uid)
            return self.async_update_and_abort(
                self._get_entry(),
                self._get_reconfigure_subentry(),
                data=data,
                title=name,
                unique_id=uid,
            )

        d = existing or {}
        schema = vol.Schema(
            {
                vol.Required("name", default=d.get("name", "")): _text_sel(),
                vol.Required(
                    "calendar", default=d.get("calendar", vol.UNDEFINED)
                ): _entity_sel("calendar"),
                vol.Optional(
                    "calendar_label",
                    description={"suggested_value": d.get("calendar_label", "")},
                ): _text_sel(),
                vol.Optional("color", default=d.get("color", "#A8C8EC")): _text_sel(),
                vol.Optional(
                    "person",
                    description={"suggested_value": d.get("person", "")},
                ): _entity_sel("person"),
                vol.Optional(
                    "notify",
                    description={"suggested_value": d.get("notify", "")},
                ): _text_sel(),
                vol.Optional(
                    "chores",
                    description={"suggested_value": d.get("chores", [])},
                ): _entity_sel("todo", multiple=True),
                vol.Optional(
                    "category",
                    default=d.get("category", DEFAULT_CALENDAR_CATEGORY),
                ): _category_sel(),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)


# ----- Extra calendar -------------------------------------------------------


def _existing_member_names(entry: ConfigEntry) -> list[str]:
    """Return member names already configured on the entry."""
    names: list[str] = []
    for sub in entry.subentries.values():
        if sub.subentry_type == SUBENTRY_MEMBER:
            n = sub.data.get("name")
            if n:
                names.append(n)
    return names


class ExtraCalendarSubentryFlow(ConfigSubentryFlow):
    """Add or reconfigure an extra-calendar subentry."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Show the form (handles both add and reconfigure submissions)."""
        existing = None
        if self.source == config_entries.SOURCE_RECONFIGURE:
            existing = dict(self._get_reconfigure_subentry().data)
        return await self._show(user_input, existing=existing)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Edit form pre-filled from the existing subentry data."""
        existing = self._get_reconfigure_subentry()
        return await self._show(user_input, existing=dict(existing.data))

    async def _show(
        self,
        user_input: dict[str, Any] | None,
        existing: dict[str, Any] | None,
    ) -> SubentryFlowResult:
        entry = self._get_entry()
        members = _existing_member_names(entry)
        if not members:
            return self.async_abort(reason="no_members")

        if user_input is not None:
            data = _strip_empties(user_input)
            parent = data.get("parent_member")
            label = data.get("label") or data.get("entity")
            uid = extra_calendar_uid(parent, data.get("entity") or label)
            title = f"{parent} · {label}"
            if existing is None:
                return self.async_create_entry(title=title, data=data, unique_id=uid)
            return self.async_update_and_abort(
                entry,
                self._get_reconfigure_subentry(),
                data=data,
                title=title,
                unique_id=uid,
            )

        d = existing or {}
        schema = vol.Schema(
            {
                vol.Required(
                    "parent_member",
                    default=d.get("parent_member", members[0]),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=members, mode=selector.SelectSelectorMode.DROPDOWN
                    )
                ),
                vol.Required(
                    "entity", default=d.get("entity", vol.UNDEFINED)
                ): _entity_sel("calendar"),
                vol.Required("label", default=d.get("label", "")): _text_sel(),
                vol.Optional(
                    "default_summary",
                    description={"suggested_value": d.get("default_summary", "")},
                ): _text_sel(),
                vol.Optional(
                    "default_description",
                    description={"suggested_value": d.get("default_description", "")},
                ): _multiline_sel(),
                vol.Optional(
                    "category",
                    default=d.get("category", DEFAULT_CALENDAR_CATEGORY),
                ): _category_sel(),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)


# ----- Shared calendar / shared chore --------------------------------------


class SharedCalendarSubentryFlow(ConfigSubentryFlow):
    """Add or reconfigure a shared-calendar subentry."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Show the form (handles both add and reconfigure submissions)."""
        existing = None
        if self.source == config_entries.SOURCE_RECONFIGURE:
            existing = dict(self._get_reconfigure_subentry().data)
        return await self._show(user_input, existing=existing)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Edit form pre-filled from the existing subentry data."""
        existing = self._get_reconfigure_subentry()
        return await self._show(user_input, existing=dict(existing.data))

    async def _show(
        self,
        user_input: dict[str, Any] | None,
        existing: dict[str, Any] | None,
    ) -> SubentryFlowResult:
        entry = self._get_entry()
        members = _existing_member_names(entry)

        if user_input is not None:
            data = _strip_empties(user_input)
            entity = data.get("entity")
            uid = shared_calendar_uid(entity)
            title = data.get("name") or entity
            if existing is None:
                return self.async_create_entry(title=title, data=data, unique_id=uid)
            return self.async_update_and_abort(
                entry,
                self._get_reconfigure_subentry(),
                data=data,
                title=title,
                unique_id=uid,
            )

        d = existing or {}
        schema = vol.Schema(
            {
                vol.Required(
                    "entity", default=d.get("entity", vol.UNDEFINED)
                ): _entity_sel("calendar"),
                vol.Required(
                    "members", default=d.get("members", members)
                ): _members_sel(members),
                vol.Optional(
                    "name",
                    description={"suggested_value": d.get("name", "")},
                ): _text_sel(),
                vol.Optional(
                    "color",
                    description={"suggested_value": d.get("color", "")},
                ): _text_sel(),
                vol.Optional(
                    "category",
                    default=d.get("category", DEFAULT_CALENDAR_CATEGORY),
                ): _category_sel(),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)


class SharedChoreSubentryFlow(ConfigSubentryFlow):
    """Add or reconfigure a shared-chore subentry."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Show the form (handles both add and reconfigure submissions)."""
        existing = None
        if self.source == config_entries.SOURCE_RECONFIGURE:
            existing = dict(self._get_reconfigure_subentry().data)
        return await self._show(user_input, existing=existing)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Edit form pre-filled from the existing subentry data."""
        existing = self._get_reconfigure_subentry()
        return await self._show(user_input, existing=dict(existing.data))

    async def _show(
        self,
        user_input: dict[str, Any] | None,
        existing: dict[str, Any] | None,
    ) -> SubentryFlowResult:
        entry = self._get_entry()
        members = _existing_member_names(entry)

        if user_input is not None:
            data = _strip_empties(user_input)
            entity = data.get("entity")
            uid = shared_chore_uid(entity)
            title = data.get("name") or entity
            if existing is None:
                return self.async_create_entry(title=title, data=data, unique_id=uid)
            return self.async_update_and_abort(
                entry,
                self._get_reconfigure_subentry(),
                data=data,
                title=title,
                unique_id=uid,
            )

        d = existing or {}
        schema = vol.Schema(
            {
                vol.Required(
                    "entity", default=d.get("entity", vol.UNDEFINED)
                ): _entity_sel("todo"),
                vol.Required(
                    "members", default=d.get("members", members)
                ): _members_sel(members),
                vol.Optional(
                    "type",
                    description={"suggested_value": d.get("type", "")},
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=["", "trash"],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(
                    "name",
                    description={"suggested_value": d.get("name", "")},
                ): _text_sel(),
                vol.Optional(
                    "color",
                    description={"suggested_value": d.get("color", "")},
                ): _text_sel(),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)


# ----- Trash ----------------------------------------------------------------


class TrashSubentryFlow(ConfigSubentryFlow):
    """Add or reconfigure a trash-collection subentry.

    UI defaults for the auto-chore reminders are **opt-in** (``False``)
    so adding a trash sensor no longer silently creates two chores.
    The legacy default-true behaviour is preserved for entries
    migrated from v1 / YAML — see ``migrate_options_to_subentries``.
    """

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Show the form (handles both add and reconfigure submissions)."""
        existing = None
        if self.source == config_entries.SOURCE_RECONFIGURE:
            existing = dict(self._get_reconfigure_subentry().data)
        return await self._show(user_input, existing=existing)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Edit form pre-filled from the existing subentry data."""
        existing = self._get_reconfigure_subentry()
        return await self._show(user_input, existing=dict(existing.data))

    async def _show(
        self,
        user_input: dict[str, Any] | None,
        existing: dict[str, Any] | None,
    ) -> SubentryFlowResult:
        entry = self._get_entry()
        if user_input is not None:
            data = _strip_empties(user_input)
            ttype = data.get("type")
            uid = trash_uid(ttype)
            title = data.get("label") or ttype
            if existing is None:
                return self.async_create_entry(title=title, data=data, unique_id=uid)
            return self.async_update_and_abort(
                entry,
                self._get_reconfigure_subentry(),
                data=data,
                title=title,
                unique_id=uid,
            )

        d = existing or {}
        schema = vol.Schema(
            {
                vol.Required(
                    "type", default=d.get("type", "rest")
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=["rest", "paper", "gft", "pmd"],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(
                    "sensor", default=d.get("sensor", vol.UNDEFINED)
                ): _entity_sel("sensor"),
                vol.Optional(
                    "label",
                    description={"suggested_value": d.get("label", "")},
                ): _text_sel(),
                vol.Optional(
                    "color",
                    description={"suggested_value": d.get("color", "")},
                ): _text_sel(),
                vol.Optional(
                    "emoji",
                    description={"suggested_value": d.get("emoji", "")},
                ): _text_sel(),
                vol.Optional(
                    "reminder_bins", default=d.get("reminder_bins", False)
                ): selector.BooleanSelector(),
                vol.Optional(
                    "reminder_kliko", default=d.get("reminder_kliko", False)
                ): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)


# ----- Meal planner ---------------------------------------------------------


class MealPlannerSubentryFlow(ConfigSubentryFlow):
    """Add or reconfigure the singleton meal-planner subentry."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Show the form (handles both add and reconfigure submissions)."""
        existing = None
        if self.source == config_entries.SOURCE_RECONFIGURE:
            existing = dict(self._get_reconfigure_subentry().data)
        elif any(
            s.subentry_type == SUBENTRY_MEAL_PLANNER
            for s in self._get_entry().subentries.values()
        ):
            return self.async_abort(reason="already_configured")
        return await self._show(user_input, existing=existing)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Edit form pre-filled from the existing subentry data."""
        existing = self._get_reconfigure_subentry()
        return await self._show(user_input, existing=dict(existing.data))

    async def _show(
        self,
        user_input: dict[str, Any] | None,
        existing: dict[str, Any] | None,
    ) -> SubentryFlowResult:
        entry = self._get_entry()
        if user_input is not None:
            data: dict[str, Any] = {}
            ai = (user_input.get("ai_task_entity") or "").strip()
            if ai:
                data["ai_task_entity"] = ai
            shopping = (user_input.get("shopping_list") or "").strip()
            if shopping:
                data["shopping_list"] = shopping
            cal = (user_input.get("meal_calendar") or "").strip()
            if cal:
                data["meal_calendar"] = cal
            mx = user_input.get("max_minutes")
            if mx:
                data["max_minutes"] = int(mx)
            for key in ("cuisines", "pantry_staples", "restrictions"):
                items = _split_lines(user_input.get(key, ""))
                if items:
                    data[key] = items
            extra_notes = (user_input.get("extra_notes") or "").strip()
            if extra_notes:
                data["extra_notes"] = extra_notes
            if existing is None:
                return self.async_create_entry(
                    title="Meal planner", data=data, unique_id=meal_planner_uid()
                )
            return self.async_update_and_abort(
                entry,
                self._get_reconfigure_subentry(),
                data=data,
                title="Meal planner",
                unique_id=meal_planner_uid(),
            )

        d = existing or {}
        schema = vol.Schema(
            {
                vol.Optional(
                    "meal_calendar",
                    description={"suggested_value": d.get("meal_calendar", "")},
                ): _entity_sel("calendar"),
                vol.Optional(
                    "ai_task_entity",
                    description={"suggested_value": d.get("ai_task_entity", "")},
                ): _entity_sel("ai_task"),
                vol.Optional(
                    "shopping_list",
                    description={"suggested_value": d.get("shopping_list", "")},
                ): _entity_sel("todo"),
                vol.Optional(
                    "max_minutes", default=d.get("max_minutes", 30)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=240, step=1, mode="box")
                ),
                vol.Optional(
                    "cuisines",
                    default="\n".join(d.get("cuisines") or []),
                ): _multiline_sel(),
                vol.Optional(
                    "pantry_staples",
                    default="\n".join(d.get("pantry_staples") or []),
                ): _multiline_sel(),
                vol.Optional(
                    "restrictions",
                    default="\n".join(d.get("restrictions") or []),
                ): _multiline_sel(),
                vol.Optional(
                    "extra_notes",
                    default=d.get("extra_notes", ""),
                ): _multiline_sel(),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)


# ----- Meal day override ----------------------------------------------------


def _existing_override_weekdays(entry: ConfigEntry) -> set[str]:
    """Return weekdays already covered by an override subentry."""
    return {
        s.data.get("weekday", "")
        for s in entry.subentries.values()
        if s.subentry_type == SUBENTRY_MEAL_DAY_OVERRIDE
    }


class MealDayOverrideSubentryFlow(ConfigSubentryFlow):
    """Add or reconfigure a single weekday override."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Show the form (handles both add and reconfigure submissions)."""
        existing = None
        if self.source == config_entries.SOURCE_RECONFIGURE:
            existing = dict(self._get_reconfigure_subentry().data)
        return await self._show(user_input, existing=existing)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Edit form pre-filled from the existing subentry data."""
        existing = self._get_reconfigure_subentry()
        return await self._show(user_input, existing=dict(existing.data))

    async def _show(
        self,
        user_input: dict[str, Any] | None,
        existing: dict[str, Any] | None,
    ) -> SubentryFlowResult:
        entry = self._get_entry()
        used = _existing_override_weekdays(entry)
        if existing is not None:
            used = used - {existing.get("weekday", "")}
        available = [w for w in WEEKDAYS if w not in used]
        if not available and existing is None:
            return self.async_abort(reason="no_weekdays_left")

        if user_input is not None:
            data: dict[str, Any] = {"weekday": user_input["weekday"]}
            note = (user_input.get("note") or "").strip()
            if note:
                data["note"] = note
            mx = user_input.get("max_minutes")
            if mx:
                data["max_minutes"] = int(mx)
            wd = data["weekday"]
            if existing is None:
                return self.async_create_entry(
                    title=wd.capitalize(),
                    data=data,
                    unique_id=meal_day_override_uid(wd),
                )
            return self.async_update_and_abort(
                entry,
                self._get_reconfigure_subentry(),
                data=data,
                title=wd.capitalize(),
                unique_id=meal_day_override_uid(wd),
            )

        d = existing or {}
        schema = vol.Schema(
            {
                vol.Required(
                    "weekday",
                    default=d.get(
                        "weekday", available[0] if available else WEEKDAYS[0]
                    ),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=available or [d.get("weekday", WEEKDAYS[0])],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(
                    "note",
                    description={"suggested_value": d.get("note", "")},
                ): _multiline_sel(),
                vol.Optional(
                    "max_minutes",
                    description={"suggested_value": d.get("max_minutes", "")},
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=240, step=1, mode="box")
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)


# ---------------------------------------------------------------------------
# Registry: maps subentry_type → flow class. Consumed by the parent
# ConfigFlow's ``async_get_supported_subentry_types``.
# ---------------------------------------------------------------------------

SUBENTRY_FLOW_REGISTRY: dict[str, type[ConfigSubentryFlow]] = {
    SUBENTRY_MEMBER: MemberSubentryFlow,
    SUBENTRY_EXTRA_CALENDAR: ExtraCalendarSubentryFlow,
    SUBENTRY_SHARED_CALENDAR: SharedCalendarSubentryFlow,
    SUBENTRY_SHARED_CHORE: SharedChoreSubentryFlow,
    SUBENTRY_TRASH: TrashSubentryFlow,
    SUBENTRY_MEAL_PLANNER: MealPlannerSubentryFlow,
    SUBENTRY_MEAL_DAY_OVERRIDE: MealDayOverrideSubentryFlow,
}


@callback
def supported_subentry_types(
    entry: ConfigEntry,
) -> dict[str, dict[str, Any]]:
    """Return the subentry-type → spec dict for the integration page.

    All known types are always returned so existing subentries keep
    their reconfigure cogwheel; the singleton / saturation guard for
    *adding* a new one happens inside the relevant flow's
    ``async_step_user`` (which aborts with a friendly reason).

    Extra-calendar is the only true exception: it cannot be added
    before any member exists because the form needs a parent dropdown
    populated from existing members.
    """
    types: dict[str, dict[str, Any]] = {
        st: {"supports_reconfigure": True} for st in SUBENTRY_FLOW_REGISTRY
    }
    if not _existing_member_names(entry):
        types.pop(SUBENTRY_EXTRA_CALENDAR, None)
    return types


# Backwards-compat re-export so callers can import everything from one place.
__all__ = [
    "SUBENTRY_FLOW_REGISTRY",
    "ExtraCalendarSubentryFlow",
    "MealDayOverrideSubentryFlow",
    "MealPlannerSubentryFlow",
    "MemberSubentryFlow",
    "SharedCalendarSubentryFlow",
    "SharedChoreSubentryFlow",
    "TrashSubentryFlow",
    "compose_conf",
    "extra_calendar_uid",
    "meal_day_override_uid",
    "meal_planner_uid",
    "member_uid",
    "migrate_options_to_subentries",
    "shared_calendar_uid",
    "shared_chore_uid",
    "supported_subentry_types",
    "trash_uid",
    "upsert_yaml",
]


# Silence unused-import on `copy`, `config_entries` (kept for typing/clarity).
_ = (copy, config_entries)
