"""Config flow for FamilyBoard.

YAML-driven for now (single-instance import). Phase 8 will replace the
import flow with a full UI/options flow with selectors and per-member
sub-steps. Until then, configuration lives in `configuration.yaml`.
"""

from __future__ import annotations

from typing import Any

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import DEVICE_NAME, DOMAIN


class FamilyBoardConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the (singleton) config flow for FamilyBoard."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """User-initiated flow — currently informational only."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=DEVICE_NAME, data={})

    async def async_step_import(self, import_data: dict[str, Any]) -> FlowResult:
        """YAML configuration import."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=DEVICE_NAME, data={})
