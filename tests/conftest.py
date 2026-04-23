"""Shared test fixtures for FamilyBoard."""

from __future__ import annotations

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom integrations in every test."""
    yield


@pytest.fixture
def sample_member() -> dict:
    """A minimal member dict used across tests."""
    return {
        "name": "Alice",
        "calendar": "calendar.alice",
        "color": "#4A90D9",
        "extra_calendars": [
            {"entity": "calendar.alice_werk", "label": "Werk"},
        ],
        "chores": ["todo.alice"],
    }


@pytest.fixture
def sample_config(sample_member) -> dict:
    """A minimal full FamilyBoard config dict."""
    return {
        "members": [
            sample_member,
            {
                "name": "Bob",
                "calendar": "calendar.bob",
                "color": "#27AE60",
                "extra_calendars": [],
                "chores": [],
            },
        ],
        "trash": [],
        "shared_calendars": [],
        "shared_chores": [],
    }
