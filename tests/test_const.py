"""Tests for custom_components.familyboard.const."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType

from custom_components.familyboard.const import (
    DEVICE_IDENTIFIER,
    DEVICE_NAME,
    DOMAIN,
    LAYOUT_OPTIONS,
    LEGACY_VIEW_STATE_MAP,
    VIEW_OPTIONS,
    get_device_info,
)


def test_get_device_info_returns_deviceinfo() -> None:
    # DeviceInfo is a TypedDict, so isinstance() is not supported; check dict.
    info = get_device_info()
    assert isinstance(info, dict)
    assert info["identifiers"] == {DEVICE_IDENTIFIER}
    assert info["name"] == DEVICE_NAME
    assert info["entry_type"] is DeviceEntryType.SERVICE


def test_view_and_layout_options_are_lists() -> None:
    assert isinstance(VIEW_OPTIONS, list) and VIEW_OPTIONS
    assert isinstance(LAYOUT_OPTIONS, list) and LAYOUT_OPTIONS
    # Stable, language-neutral keys; user-visible labels live in translations.
    assert VIEW_OPTIONS == [
        "today",
        "2_days",
        "3_days",
        "work_week",
        "week",
        "two_weeks",
        "month",
    ]
    assert LAYOUT_OPTIONS == ["list", "agenda"]


def test_legacy_view_state_map_migrates_removed_keys() -> None:
    # Restored states from earlier releases must round-trip into the
    # current `VIEW_OPTIONS` keys without losing the user's selection.
    assert LEGACY_VIEW_STATE_MAP["tomorrow"] == "today"
    assert LEGACY_VIEW_STATE_MAP["today_tomorrow"] == "2_days"
    assert LEGACY_VIEW_STATE_MAP["Vandaag + Morgen"] == "2_days"
    for mapped in LEGACY_VIEW_STATE_MAP.values():
        assert mapped in VIEW_OPTIONS


def test_domain_is_familyboard() -> None:
    assert DOMAIN == "familyboard"
