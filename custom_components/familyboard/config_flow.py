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


def _select(options: list[str], multiple: bool = False) -> selector.Selector:
    """Return a dropdown selector populated with ``options``."""
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options,
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

        ``import_data`` is the validated ``familyboard:`` block.
        """
        await self.async_set_unique_id(DOMAIN)
        # If an entry already exists, refresh its options from YAML.
        for entry in self._async_current_entries():
            self.hass.config_entries.async_update_entry(
                entry, options=_normalize_options(import_data)
            )
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
        return FamilyBoardOptionsFlow(config_entry)


def _normalize_options(raw: dict[str, Any]) -> dict[str, Any]:
    """Coerce a (possibly-partial) YAML/options dict into the options shape."""
    base = default_options()
    base.update(
        {
            "members": list(raw.get("members") or []),
            "trash": list(raw.get("trash") or []),
            "shared_calendars": list(raw.get("shared_calendars") or []),
            "shared_chores": list(raw.get("shared_chores") or []),
        }
    )
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

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Snapshot the current options into a working copy for editing."""
        self.config_entry = config_entry
        self._options: dict[str, Any] = copy.deepcopy(
            dict(config_entry.options) or default_options()
        )
        for key in ("members", "trash", "shared_calendars", "shared_chores"):
            self._options.setdefault(key, [])
        # Editing cursors
        self._editing_member_index: int | None = None
        self._editing_extra_index: int | None = None
        self._editing_trash_index: int | None = None
        self._editing_shared_cal_index: int | None = None
        self._editing_shared_chore_index: int | None = None

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
                "save",
            ],
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
        choices = ["__add__", *labels, "__back__"]

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
                {vol.Required("action"): _select(["edit", "extras", "remove", "back"])}
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
        choices = ["__add__", *labels, "__back__"]

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
        choices = ["__add__", *labels, "__back__"]

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
        choices = ["__add__", *labels, "__back__"]

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
        choices = ["__add__", *labels, "__back__"]

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


__all__ = ["OPTIONS_SCHEMA", "FamilyBoardConfigFlow", "FamilyBoardOptionsFlow"]
