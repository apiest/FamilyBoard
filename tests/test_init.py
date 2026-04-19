"""Smoke test for FamilyBoard integration setup via YAML config."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component

from custom_components.familyboard.const import DOMAIN


async def test_setup_with_yaml_config(hass: HomeAssistant, sample_config) -> None:
    """Loading the integration with a minimal YAML config should succeed."""
    assert await async_setup_component(hass, DOMAIN, {DOMAIN: sample_config})
    await hass.async_block_till_done()

    # Integration data is populated
    assert DOMAIN in hass.data
    assert hass.data[DOMAIN].get("config") is not None

    # Services are registered
    assert hass.services.has_service(DOMAIN, "add_event")
    assert hass.services.has_service(DOMAIN, "snooze_test")
    assert hass.services.has_service(DOMAIN, "cancel_reminder")


async def test_filter_select_entity_present(hass: HomeAssistant, sample_config) -> None:
    """The calendar filter select should be created with member options."""
    assert await async_setup_component(hass, DOMAIN, {DOMAIN: sample_config})
    await hass.async_block_till_done()

    # Look up by unique_id since the actual entity_id depends on translations
    # (with `has_entity_name = True` HA derives the slug from the device + name).
    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id("select", DOMAIN, "familyboard_calendar")
    assert entity_id is not None, "calendar filter select entity not registered"

    state = hass.states.get(entity_id)
    assert state is not None
    assert "Alles" in state.attributes["options"]
    assert "Berry" in state.attributes["options"]
    assert "Sylvia" in state.attributes["options"]
