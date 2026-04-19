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
        "name": "Berry",
        "calendar": "calendar.berry",
        "color": "#4A90D9",
        "extra_calendars": [
            {"entity": "calendar.berry_werk", "label": "Werk"},
        ],
        "chores": ["todo.berry"],
    }


@pytest.fixture
def sample_config(sample_member) -> dict:
    """A minimal full FamilyBoard config dict."""
    return {
        "members": [
            sample_member,
            {
                "name": "Sylvia",
                "calendar": "calendar.sylvia",
                "color": "#27AE60",
                "extra_calendars": [],
                "chores": [],
            },
        ],
        "trash": [],
        "shared_calendars": [],
        "shared_chores": [],
    }
