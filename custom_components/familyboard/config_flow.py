"""Config + options flow for FamilyBoard.

Singleton config entry. Members, trash collections, shared calendars and
shared chores can all be managed from the UI via the options flow. YAML
configuration is still supported and is imported into the options on first
run; subsequent edits via the UI take precedence.
"""

from __future__ import annotations

import copy
from typing import Any

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
import voluptuous as vol

from .const import DEVICE_NAME, DOMAIN
from .schemas import (
    EXTRA_CALENDAR_SCHEMA,
    MEAL_PLANNER_SCHEMA,
    MEMBER_SCHEMA,
    OPTIONS_SCHEMA,
    SHARED_CALENDAR_SCHEMA,
    SHARED_CHORE_SCHEMA,
    TRASH_SCHEMA,
    default_options,
)

# ---------------------------------------------------------------------------
# Selector helpers
# ---------------------------------------------------------------------------


def _text() -> selector.Selector:
    """Return a single-line text selector."""
    return selector.TextSelector(selector.TextSelectorConfig())


def _multiline() -> selector.Selector:
    """Return a multi-line text selector."""
    return selector.TextSelector(selector.TextSelectorConfig(multiline=True))


def _entity(domain: str, multiple: bool = False) -> selector.Selector:
    """Return an entity selector restricted to ``domain``."""
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain=domain, multiple=multiple)
    )


def _bool() -> selector.Selector:
    """Return a boolean selector."""
    return selector.BooleanSelector()


def _select(
    options: list[str] | list[tuple[str, str]],
    multiple: bool = False,
) -> selector.Selector:
    """Return a dropdown selector populated with ``options``.

    Items may be plain strings or ``(value, label)`` tuples for friendly labels.
    """
    normalized: list[Any] = [
        selector.SelectOptionDict(value=opt[0], label=opt[1])
        if isinstance(opt, tuple)
        else opt
        for opt in options
    ]
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=normalized,
            multiple=multiple,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


# ---------------------------------------------------------------------------
# Config flow
# ---------------------------------------------------------------------------


class FamilyBoardConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Singleton config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Create the singleton entry; configuration happens via the options flow."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=DEVICE_NAME,
            data={},
            options=default_options(),
        )

    async def async_step_import(self, import_data: dict[str, Any]) -> FlowResult:
        """Import options from YAML.

        ``import_data`` is the validated ``familyboard:`` block. Existing
        UI-only options (e.g. ``meal_calendar`` set via the General step)
        are preserved when YAML does not explicitly set them.
        """
        await self.async_set_unique_id(DOMAIN)
        for entry in self._async_current_entries():
            merged = _normalize_options(import_data, existing=dict(entry.options))
            self.hass.config_entries.async_update_entry(entry, options=merged)
            return self.async_abort(reason="single_instance_allowed")
        return self.async_create_entry(
            title=DEVICE_NAME,
            data={},
            options=_normalize_options(import_data),
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the options flow for an existing FamilyBoard entry."""
        return FamilyBoardOptionsFlow()


def _normalize_options(
    raw: dict[str, Any], existing: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Coerce a (possibly-partial) YAML/options dict into the options shape.

    When ``existing`` is provided, UI-only keys absent from ``raw`` are
    carried over so a YAML re-import does not wipe values configured
    through the options flow (e.g. ``meal_calendar``).
    """
    base = default_options()
    base.update(
        {
            "members": list(raw.get("members") or []),
            "trash": list(raw.get("trash") or []),
            "shared_calendars": list(raw.get("shared_calendars") or []),
            "shared_chores": list(raw.get("shared_chores") or []),
        }
    )
    meal = raw.get("meal_calendar")
    if not meal and existing:
        meal = existing.get("meal_calendar")
    if meal:
        base["meal_calendar"] = meal
    planner = raw.get("meal_planner")
    if not planner and existing:
        planner = existing.get("meal_planner")
    if planner:
        base["meal_planner"] = planner
    return base


# ---------------------------------------------------------------------------
# Options flow
# ---------------------------------------------------------------------------


class FamilyBoardOptionsFlow(config_entries.OptionsFlow):
    """Menu-driven options flow.

    Working state lives in ``self._options`` (a deep copy of the entry
    options) and is committed only when the user picks "Save" on the main
    menu.
    """

    def __init__(self) -> None:
        """Initialise editing cursors; options are snapshotted lazily.

        ``self.config_entry`` is a read-only property populated by Home
        Assistant after construction, so we cannot read entry options here.
        """
        self._options_cache: dict[str, Any] | None = None
        # Editing cursors
        self._editing_member_index: int | None = None
        self._editing_extra_index: int | None = None
        self._editing_trash_index: int | None = None
        self._editing_shared_cal_index: int | None = None
        self._editing_shared_chore_index: int | None = None

    @property
    def _options(self) -> dict[str, Any]:
        """Return the working options dict, snapshotting on first access."""
        if self._options_cache is None:
            self._options_cache = copy.deepcopy(
                dict(self.config_entry.options) or default_options()
            )
            for key in ("members", "trash", "shared_calendars", "shared_chores"):
                self._options_cache.setdefault(key, [])
        return self._options_cache

    # ------------------------------------------------------------------
    # Top-level menu
    # ------------------------------------------------------------------

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show the top-level options menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "members",
                "trash",
                "shared_calendars",
                "shared_chores",
                "general",
                "meal_planner",
                "save",
            ],
        )

    async def async_step_general(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Edit miscellaneous integration-wide settings (e.g. meal calendar).

        Persists immediately on submit so the user does not need to also
        click "Save and exit" — matching the behaviour of the per-entity
        edit steps.
        """
        if user_input is not None:
            meal = (user_input.get("meal_calendar") or "").strip()
            if meal:
                self._options["meal_calendar"] = meal
            else:
                self._options.pop("meal_calendar", None)
            return self.async_create_entry(title="", data=self._options)

        return self.async_show_form(
            step_id="general",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        "meal_calendar",
                        default=self._options.get("meal_calendar", ""),
                    ): _entity("calendar"),
                }
            ),
        )

    async def async_step_meal_planner(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Edit the AI meal-planner configuration (Phase 2.5).

        Multi-line text fields are split on newlines into a list. Empty
        fields fall back to the defaults baked into ``const.py`` at
        prompt-build time. ``day_overrides`` is preserved from the
        existing options (YAML-only for v1).
        """
        existing = self._options.get("meal_planner") or {}
        errors: dict[str, str] = {}

        if user_input is not None:
            data: dict[str, Any] = {}
            ai_entity = (user_input.get("ai_task_entity") or "").strip()
            if not ai_entity:
                # Empty submit clears the planner entirely.
                self._options.pop("meal_planner", None)
                return self.async_create_entry(title="", data=self._options)
            data["ai_task_entity"] = ai_entity

            shopping = (user_input.get("shopping_list") or "").strip()
            if shopping:
                data["shopping_list"] = shopping

            max_min = user_input.get("max_minutes")
            if max_min:
                data["max_minutes"] = int(max_min)

            for key in ("cuisines", "pantry_staples", "restrictions"):
                items = _split_lines(user_input.get(key, ""))
                if items:
                    data[key] = items

            extra_notes = (user_input.get("extra_notes") or "").strip()
            if extra_notes:
                data["extra_notes"] = extra_notes

            # Preserve day_overrides set via YAML (no UI for v1).
            if existing.get("day_overrides"):
                data["day_overrides"] = existing["day_overrides"]

            try:
                validated = MEAL_PLANNER_SCHEMA(data)
            except vol.Invalid as err:
                errors["base"] = str(err)
            else:
                self._options["meal_planner"] = validated
                return self.async_create_entry(title="", data=self._options)

        return self.async_show_form(
            step_id="meal_planner",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        "ai_task_entity",
                        default=existing.get("ai_task_entity", ""),
                    ): _entity("ai_task"),
                    vol.Optional(
                        "shopping_list",
                        default=existing.get("shopping_list", ""),
                    ): _entity("todo"),
                    vol.Optional(
                        "max_minutes",
                        default=existing.get("max_minutes", 30),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1, max=240, step=1, mode="box"
                        )
                    ),
                    vol.Optional(
                        "cuisines",
                        default="\n".join(existing.get("cuisines") or []),
                    ): _multiline(),
                    vol.Optional(
                        "pantry_staples",
                        default="\n".join(existing.get("pantry_staples") or []),
                    ): _multiline(),
                    vol.Optional(
                        "restrictions",
                        default="\n".join(existing.get("restrictions") or []),
                    ): _multiline(),
                    vol.Optional(
                        "extra_notes",
                        default=existing.get("extra_notes", ""),
                    ): _multiline(),
                }
            ),
            errors=errors,
        )

    async def async_step_save(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Persist the working copy as the new entry options."""
        return self.async_create_entry(title="", data=self._options)

    # ------------------------------------------------------------------
    # Members
    # ------------------------------------------------------------------

    async def async_step_members(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """List members and let the user add or pick one to edit."""
        members = self._options["members"]
        labels = [f"{i}: {m['name']}" for i, m in enumerate(members)]
        choices: list[str | tuple[str, str]] = [
            ("__add__", "➕ Add new member"),  # noqa: RUF001
            *labels,
            ("__back__", "← Back"),
        ]

        if user_input is not None:
            choice = user_input["action"]
            if choice == "__add__":
                self._editing_member_index = None
                return await self.async_step_member_edit()
            if choice == "__back__":
                return await self.async_step_init()
            self._editing_member_index = labels.index(choice)
            return await self.async_step_member_action()

        return self.async_show_form(
            step_id="members",
            data_schema=vol.Schema({vol.Required("action"): _select(choices)}),
            description_placeholders={"count": str(len(members))},
        )

    async def async_step_member_action(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Choose what to do with the currently selected member."""
        idx = self._editing_member_index
        assert idx is not None
        member = self._options["members"][idx]

        if user_input is not None:
            action = user_input["action"]
            if action == "edit":
                return await self.async_step_member_edit()
            if action == "extras":
                return await self.async_step_member_extras()
            if action == "remove":
                self._options["members"].pop(idx)
                self._editing_member_index = None
                return await self.async_step_members()
            return await self.async_step_members()

        return self.async_show_form(
            step_id="member_action",
            data_schema=vol.Schema(
                {
                    vol.Required("action"): _select(
                        [
                            ("edit", "✏️ Edit"),
                            ("extras", "📅 Extra calendars"),
                            ("remove", "🗑️ Remove"),
                            ("back", "← Back"),
                        ]
                    )
                }
            ),
            description_placeholders={"name": member["name"]},
        )

    async def async_step_member_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Add or edit the basic fields of a member."""
        idx = self._editing_member_index
        existing = self._options["members"][idx] if idx is not None else None

        errors: dict[str, str] = {}
        if user_input is not None:
            data = _strip_empties(user_input)
            data.setdefault("color", "#4A90D9")
            # preserve extras across basic-fields edits
            if existing is not None:
                data.setdefault("extra_calendars", existing.get("extra_calendars", []))
            data.setdefault("chores", data.get("chores", []) or [])
            try:
                validated = MEMBER_SCHEMA(data)
            except vol.Invalid as err:
                errors["base"] = str(err)
            else:
                if idx is None:
                    self._options["members"].append(validated)
                    self._editing_member_index = len(self._options["members"]) - 1
                else:
                    self._options["members"][idx] = validated
                return await self.async_step_members()

        defaults = existing or {}
        schema = vol.Schema(
            {
                vol.Required("name", default=defaults.get("name", "")): _text(),
                vol.Required(
                    "calendar", default=defaults.get("calendar", vol.UNDEFINED)
                ): _entity("calendar"),
                vol.Optional(
                    "calendar_label",
                    description={"suggested_value": defaults.get("calendar_label", "")},
                ): _text(),
                vol.Optional(
                    "calendar_default_summary",
                    description={
                        "suggested_value": defaults.get("calendar_default_summary", "")
                    },
                ): _text(),
                vol.Optional(
                    "calendar_default_description",
                    description={
                        "suggested_value": defaults.get(
                            "calendar_default_description", ""
                        )
                    },
                ): _multiline(),
                vol.Optional(
                    "color", default=defaults.get("color", "#4A90D9")
                ): _text(),
                vol.Optional(
                    "person",
                    description={"suggested_value": defaults.get("person")},
                ): _entity("person"),
                vol.Optional(
                    "notify",
                    description={"suggested_value": defaults.get("notify", "")},
                ): _text(),
                vol.Optional(
                    "chores",
                    description={"suggested_value": defaults.get("chores", [])},
                ): _entity("todo", multiple=True),
            }
        )
        return self.async_show_form(
            step_id="member_edit", data_schema=schema, errors=errors
        )

    # ------------------------------------------------------------------
    # Member extras
    # ------------------------------------------------------------------

    async def async_step_member_extras(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """List the member's extra calendars."""
        idx = self._editing_member_index
        assert idx is not None
        extras = self._options["members"][idx].setdefault("extra_calendars", [])
        labels = [f"{i}: {e.get('label') or e['entity']}" for i, e in enumerate(extras)]
        choices: list[str | tuple[str, str]] = [
            ("__add__", "➕ Add new extra calendar"),  # noqa: RUF001
            *labels,
            ("__back__", "← Back"),
        ]

        if user_input is not None:
            choice = user_input["action"]
            if choice == "__add__":
                self._editing_extra_index = None
                return await self.async_step_member_extra_edit()
            if choice == "__back__":
                return await self.async_step_member_action()
            self._editing_extra_index = labels.index(choice)
            return await self.async_step_member_extra_edit()

        return self.async_show_form(
            step_id="member_extras",
            data_schema=vol.Schema({vol.Required("action"): _select(choices)}),
        )

    async def async_step_member_extra_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Add, edit or remove an extra calendar for the current member."""
        midx = self._editing_member_index
        assert midx is not None
        extras = self._options["members"][midx].setdefault("extra_calendars", [])
        eidx = self._editing_extra_index
        existing = extras[eidx] if eidx is not None else None

        errors: dict[str, str] = {}
        if user_input is not None:
            data = _strip_empties(user_input)
            if data.pop("__remove__", False) and eidx is not None:
                extras.pop(eidx)
                self._editing_extra_index = None
                return await self.async_step_member_extras()
            try:
                validated = EXTRA_CALENDAR_SCHEMA(data)
            except vol.Invalid as err:
                errors["base"] = str(err)
            else:
                if eidx is None:
                    extras.append(validated)
                else:
                    extras[eidx] = validated
                return await self.async_step_member_extras()

        defaults = existing or {}
        schema_dict: dict = {
            vol.Required(
                "entity", default=defaults.get("entity", vol.UNDEFINED)
            ): _entity("calendar"),
            vol.Required("label", default=defaults.get("label", "")): _text(),
            vol.Optional(
                "default_summary",
                description={"suggested_value": defaults.get("default_summary", "")},
            ): _text(),
            vol.Optional(
                "default_description",
                description={
                    "suggested_value": defaults.get("default_description", "")
                },
            ): _multiline(),
        }
        if existing is not None:
            schema_dict[vol.Optional("__remove__", default=False)] = _bool()
        return self.async_show_form(
            step_id="member_extra_edit",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Trash
    # ------------------------------------------------------------------

    async def async_step_trash(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """List configured trash sensors."""
        items = self._options["trash"]
        labels = [
            f"{i}: {t.get('label') or t['type']} ({t['sensor']})"
            for i, t in enumerate(items)
        ]
        choices: list[str | tuple[str, str]] = [
            ("__add__", "➕ Add new trash collection"),  # noqa: RUF001
            *labels,
            ("__back__", "← Back"),
        ]

        if user_input is not None:
            choice = user_input["action"]
            if choice == "__add__":
                self._editing_trash_index = None
                return await self.async_step_trash_edit()
            if choice == "__back__":
                return await self.async_step_init()
            self._editing_trash_index = labels.index(choice)
            return await self.async_step_trash_edit()

        return self.async_show_form(
            step_id="trash",
            data_schema=vol.Schema({vol.Required("action"): _select(choices)}),
        )

    async def async_step_trash_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Add, edit or remove a trash sensor entry."""
        idx = self._editing_trash_index
        existing = self._options["trash"][idx] if idx is not None else None

        errors: dict[str, str] = {}
        if user_input is not None:
            data = _strip_empties(user_input)
            if data.pop("__remove__", False) and idx is not None:
                self._options["trash"].pop(idx)
                self._editing_trash_index = None
                return await self.async_step_trash()
            try:
                validated = TRASH_SCHEMA(data)
            except vol.Invalid as err:
                errors["base"] = str(err)
            else:
                if idx is None:
                    self._options["trash"].append(validated)
                else:
                    self._options["trash"][idx] = validated
                return await self.async_step_trash()

        defaults = existing or {}
        schema_dict: dict = {
            vol.Required("type", default=defaults.get("type", "rest")): _select(
                ["rest", "paper", "gft", "pmd"]
            ),
            vol.Required(
                "sensor", default=defaults.get("sensor", vol.UNDEFINED)
            ): _entity("sensor"),
            vol.Optional(
                "label",
                description={"suggested_value": defaults.get("label", "")},
            ): _text(),
            vol.Optional(
                "color",
                description={"suggested_value": defaults.get("color", "")},
            ): _text(),
            vol.Optional(
                "emoji",
                description={"suggested_value": defaults.get("emoji", "")},
            ): _text(),
        }
        if existing is not None:
            schema_dict[vol.Optional("__remove__", default=False)] = _bool()
        return self.async_show_form(
            step_id="trash_edit",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Shared calendars
    # ------------------------------------------------------------------

    async def async_step_shared_calendars(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """List shared calendars."""
        items = self._options["shared_calendars"]
        labels = [f"{i}: {c.get('name') or c['entity']}" for i, c in enumerate(items)]
        choices: list[str | tuple[str, str]] = [
            ("__add__", "➕ Add new shared calendar"),  # noqa: RUF001
            *labels,
            ("__back__", "← Back"),
        ]

        if user_input is not None:
            choice = user_input["action"]
            if choice == "__add__":
                self._editing_shared_cal_index = None
                return await self.async_step_shared_calendar_edit()
            if choice == "__back__":
                return await self.async_step_init()
            self._editing_shared_cal_index = labels.index(choice)
            return await self.async_step_shared_calendar_edit()

        return self.async_show_form(
            step_id="shared_calendars",
            data_schema=vol.Schema({vol.Required("action"): _select(choices)}),
        )

    async def async_step_shared_calendar_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Add, edit or remove a shared calendar entry."""
        idx = self._editing_shared_cal_index
        existing = self._options["shared_calendars"][idx] if idx is not None else None
        member_names = [m["name"] for m in self._options["members"]]

        errors: dict[str, str] = {}
        if user_input is not None:
            data = _strip_empties(user_input)
            if data.pop("__remove__", False) and idx is not None:
                self._options["shared_calendars"].pop(idx)
                self._editing_shared_cal_index = None
                return await self.async_step_shared_calendars()
            try:
                validated = SHARED_CALENDAR_SCHEMA(data)
            except vol.Invalid as err:
                errors["base"] = str(err)
            else:
                if idx is None:
                    self._options["shared_calendars"].append(validated)
                else:
                    self._options["shared_calendars"][idx] = validated
                return await self.async_step_shared_calendars()

        defaults = existing or {}
        schema_dict: dict = {
            vol.Required(
                "entity", default=defaults.get("entity", vol.UNDEFINED)
            ): _entity("calendar"),
            vol.Required(
                "members", default=defaults.get("members", member_names)
            ): _select(member_names or ["(no members)"], multiple=True),
            vol.Optional(
                "name",
                description={"suggested_value": defaults.get("name", "")},
            ): _text(),
            vol.Optional(
                "color",
                description={"suggested_value": defaults.get("color", "")},
            ): _text(),
        }
        if existing is not None:
            schema_dict[vol.Optional("__remove__", default=False)] = _bool()
        return self.async_show_form(
            step_id="shared_calendar_edit",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Shared chores
    # ------------------------------------------------------------------

    async def async_step_shared_chores(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """List shared chores."""
        items = self._options["shared_chores"]
        labels = [f"{i}: {c.get('name') or c['entity']}" for i, c in enumerate(items)]
        choices: list[str | tuple[str, str]] = [
            ("__add__", "➕ Add new shared chore"),  # noqa: RUF001
            *labels,
            ("__back__", "← Back"),
        ]

        if user_input is not None:
            choice = user_input["action"]
            if choice == "__add__":
                self._editing_shared_chore_index = None
                return await self.async_step_shared_chore_edit()
            if choice == "__back__":
                return await self.async_step_init()
            self._editing_shared_chore_index = labels.index(choice)
            return await self.async_step_shared_chore_edit()

        return self.async_show_form(
            step_id="shared_chores",
            data_schema=vol.Schema({vol.Required("action"): _select(choices)}),
        )

    async def async_step_shared_chore_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Add, edit or remove a shared chore entry."""
        idx = self._editing_shared_chore_index
        existing = self._options["shared_chores"][idx] if idx is not None else None
        member_names = [m["name"] for m in self._options["members"]]

        errors: dict[str, str] = {}
        if user_input is not None:
            data = _strip_empties(user_input)
            if data.pop("__remove__", False) and idx is not None:
                self._options["shared_chores"].pop(idx)
                self._editing_shared_chore_index = None
                return await self.async_step_shared_chores()
            try:
                validated = SHARED_CHORE_SCHEMA(data)
            except vol.Invalid as err:
                errors["base"] = str(err)
            else:
                if idx is None:
                    self._options["shared_chores"].append(validated)
                else:
                    self._options["shared_chores"][idx] = validated
                return await self.async_step_shared_chores()

        defaults = existing or {}
        schema_dict: dict = {
            vol.Required(
                "entity", default=defaults.get("entity", vol.UNDEFINED)
            ): _entity("todo"),
            vol.Required(
                "members", default=defaults.get("members", member_names)
            ): _select(member_names or ["(no members)"], multiple=True),
            vol.Optional(
                "type",
                description={"suggested_value": defaults.get("type", "")},
            ): _select(["", "trash"]),
            vol.Optional(
                "name",
                description={"suggested_value": defaults.get("name", "")},
            ): _text(),
            vol.Optional(
                "color",
                description={"suggested_value": defaults.get("color", "")},
            ): _text(),
        }
        if existing is not None:
            schema_dict[vol.Optional("__remove__", default=False)] = _bool()
        return self.async_show_form(
            step_id="shared_chore_edit",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _strip_empties(data: dict[str, Any]) -> dict[str, Any]:
    """Drop keys whose value is None, empty string, or empty list."""
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
    """Split a multi-line text field into a stripped list, dropping empties."""
    if not value:
        return []
    return [line.strip() for line in value.splitlines() if line.strip()]


__all__ = ["OPTIONS_SCHEMA", "FamilyBoardConfigFlow", "FamilyBoardOptionsFlow"]
