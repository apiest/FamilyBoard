"""Tests for the FR-12 event countdown entities."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component

from custom_components.familyboard.const import DOMAIN


async def test_countdown_entities_registered(
    hass: HomeAssistant, sample_config
) -> None:
    """The countdown text + datetime entities should be created on setup."""
    assert await async_setup_component(hass, DOMAIN, {DOMAIN: sample_config})
    await hass.async_block_till_done()

    ent_reg = er.async_get(hass)

    label_id = ent_reg.async_get_entity_id(
        "text", DOMAIN, "familyboard_countdown_label"
    )
    assert label_id is not None, "countdown label text entity not registered"
    label_entry = ent_reg.async_get(label_id)
    assert label_entry is not None
    assert label_entry.translation_key == "countdown_label"

    label_state = hass.states.get(label_id)
    assert label_state is not None
    # Empty by default so the card stays hidden until the user sets one.
    assert label_state.state == ""

    date_id = ent_reg.async_get_entity_id(
        "datetime", DOMAIN, "familyboard_countdown_date"
    )
    assert date_id is not None, "countdown date entity not registered"
    date_entry = ent_reg.async_get(date_id)
    assert date_entry is not None
    assert date_entry.translation_key == "countdown_date"

    date_state = hass.states.get(date_id)
    assert date_state is not None
    # Default is roughly today + 7d; just confirm it's a parseable datetime.
    assert date_state.state not in ("", "unknown", "unavailable")
