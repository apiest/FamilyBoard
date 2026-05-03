"""Config + options flow for FamilyBoard.

Singleton config entry. All user-managed lists (members, extra
calendars, shared calendars / chores, trash sensors, meal planner +
day overrides) are exposed as **subentries** under the integration
page — see :mod:`.subentries` for the per-type flow classes.

The options flow itself is intentionally a thin placeholder:
everything moved to subentries. YAML configuration is still supported
and is upserted into subentries by stable ``unique_id`` on every HA
start.
"""

from __future__ import annotations

from typing import Any

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
import voluptuous as vol

from .const import CONFIG_ENTRY_VERSION, DEVICE_NAME, DOMAIN
from .schemas import OPTIONS_SCHEMA
from .subentries import (
    SUBENTRY_FLOW_REGISTRY,
    supported_subentry_types,
    upsert_yaml,
)


class FamilyBoardConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Singleton config flow."""

    VERSION = CONFIG_ENTRY_VERSION

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: config_entries.ConfigEntry
    ) -> dict[str, type[config_entries.ConfigSubentryFlow]]:
        """Return the subentry types this entry supports.

        HA renders the chooser dialog from this dict when the user
        clicks the plus icon on the integration page. Singleton / fully-saturated
        types are filtered out by ``supported_subentry_types``.
        """
        allowed = supported_subentry_types(config_entry)
        return {st: SUBENTRY_FLOW_REGISTRY[st] for st in allowed}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Create the singleton entry; configuration happens via subentries."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=DEVICE_NAME,
            data={},
            options={},
        )

    async def async_step_import(self, import_data: dict[str, Any]) -> FlowResult:
        """Import options from YAML.

        ``import_data`` is the validated ``familyboard:`` block. We
        upsert each item into a subentry by stable ``unique_id``.
        UI-only subentries (no YAML twin) are preserved across
        re-imports.
        """
        await self.async_set_unique_id(DOMAIN)
        for entry in self._async_current_entries():
            await upsert_yaml(self.hass, entry, import_data)
            return self.async_abort(reason="single_instance_allowed")

        # No existing entry yet — create an empty entry; the YAML is
        # applied from ``async_setup_entry`` once the entry exists in
        # the registry (we cannot upsert here because the entry is
        # not yet stored).
        result = self.async_create_entry(title=DEVICE_NAME, data={}, options={})
        self.hass.data.setdefault(DOMAIN, {})["pending_yaml_import"] = import_data
        return result

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the options flow for an existing FamilyBoard entry."""
        return FamilyBoardOptionsFlow()


class FamilyBoardOptionsFlow(config_entries.OptionsFlow):
    """Placeholder options flow.

    All FamilyBoard configuration is now managed via subentries on the
    integration page. The options flow exists so HA's "Configure"
    button keeps working, but the form is informational only.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show an informational placeholder."""
        if user_input is not None:
            return self.async_create_entry(title="", data={})
        return self.async_show_form(step_id="init", data_schema=vol.Schema({}))


__all__ = ["OPTIONS_SCHEMA", "FamilyBoardConfigFlow", "FamilyBoardOptionsFlow"]
