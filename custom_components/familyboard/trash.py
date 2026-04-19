"""Trash chore auto-creation engine for FamilyBoard.

Watches trash sensors and automatically creates todo items on the
configured shared_chores entity with type: trash.  Two chores per
trash type:
  1. Prullenbakken legen — due evening before collection (default 21:00)
  2. Kliko aan de weg zetten — due morning of collection (default 07:00)

Deduplicates via persistent storage and auto-completes after collection day.
"""

from __future__ import annotations

import logging
from datetime import date as date_cls, datetime, timedelta
from typing import Any

from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    TRASH_CHORE_STORAGE_KEY,
    TRASH_CHORE_STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_EMOJIS = {
    "rest": "\U0001f5d1\ufe0f",
    "paper": "\U0001f4c4",
    "gft": "\U0001f33f",
    "pmd": "\u267b\ufe0f",
}


class TrashChoreManager:
    """Creates and manages trash chores on a shared todo entity."""

    def __init__(
        self,
        hass: HomeAssistant,
        trash_config: list[dict],
        shared_chores: list[dict],
    ) -> None:
        self.hass = hass
        self.trash_config = trash_config
        # Find the shared_chores entity with type: trash
        self._trash_todo_entity: str | None = None
        for sc in shared_chores:
            if sc.get("type") == "trash":
                self._trash_todo_entity = sc["entity"]
                break
        self._store: Store = Store(
            hass, TRASH_CHORE_STORAGE_VERSION, TRASH_CHORE_STORAGE_KEY
        )
        # Tracking: {dedup_key: {summary, due, collection_date, todo_entity, uid, type}}
        self._tracked: dict[str, dict[str, Any]] = {}
        self._unsub_listeners: list[CALLBACK_TYPE] = []

    async def async_start(self) -> None:
        """Load state and start listening to trash sensors."""
        loaded = await self._store.async_load()
        if loaded:
            self._tracked = loaded.get("tracked", {})

        if not self._trash_todo_entity or not self.trash_config:
            return

        sensor_ids = [t["sensor"] for t in self.trash_config]
        self._unsub_listeners.append(
            async_track_state_change_event(
                self.hass, sensor_ids, self._handle_sensor_change
            )
        )

        # Also check current sensor states on startup
        await self._check_all_sensors()

    async def async_stop(self) -> None:
        """Unsubscribe listeners."""
        for unsub in self._unsub_listeners:
            unsub()
        self._unsub_listeners.clear()

    @callback
    def _handle_sensor_change(self, event: Event) -> None:
        """Handle trash sensor state changes."""
        self.hass.async_create_task(self._check_all_sensors())

    async def _check_all_sensors(self) -> None:
        """Check all trash sensors and create chores as needed."""
        if not self._trash_todo_entity:
            return

        for t in self.trash_config:
            sensor_id = t["sensor"]
            ttype = t["type"]
            state = self.hass.states.get(sensor_id)
            if state is None:
                continue
            raw = state.state
            if not raw or raw in ("unknown", "unavailable", "none"):
                continue
            try:
                collection_date = self._parse_date(raw)
            except (ValueError, TypeError):
                _LOGGER.debug(
                    "TrashChoreManager: cannot parse date from %s: %s",
                    sensor_id,
                    raw,
                )
                continue

            today = dt_util.now().date()
            if collection_date < today:
                continue  # Past collection, skip

            attrs = state.attributes
            label = (
                t.get("label")
                or attrs.get("label")
                or ttype.capitalize()
            )
            emoji = (
                t.get("emoji")
                or attrs.get("emoji")
                or DEFAULT_EMOJIS.get(ttype, "\U0001f5d1\ufe0f")
            )

            # Chore 1: Prullenbakken legen — evening before
            due_bins = (collection_date - timedelta(days=1)).isoformat()
            summary_bins = f"{emoji} Prullenbakken legen ({label})"
            await self._ensure_chore(
                ttype, "bins", summary_bins, due_bins, collection_date
            )

            # Chore 2: Kliko aan de weg zetten — morning of collection
            due_kliko = collection_date.isoformat()
            summary_kliko = f"{emoji} Kliko aan de weg zetten ({label})"
            await self._ensure_chore(
                ttype, "kliko", summary_kliko, due_kliko, collection_date
            )

        await self._save()

    async def _ensure_chore(
        self,
        ttype: str,
        chore_kind: str,
        summary: str,
        due: str,
        collection_date: date_cls,
    ) -> None:
        """Create a chore if it doesn't already exist (dedup)."""
        dedup_key = f"{ttype}_{chore_kind}_{due}"
        if dedup_key in self._tracked:
            return  # Already created

        try:
            await self.hass.services.async_call(
                "todo",
                "add_item",
                {
                    "item": summary,
                    "due_date": due,
                },
                target={"entity_id": self._trash_todo_entity},
                blocking=True,
            )
            self._tracked[dedup_key] = {
                "summary": summary,
                "due": due,
                "collection_date": collection_date.isoformat(),
                "todo_entity": self._trash_todo_entity,
                "type": ttype,
                "kind": chore_kind,
            }
            _LOGGER.info(
                "TrashChoreManager: created chore '%s' due %s on %s",
                summary,
                due,
                self._trash_todo_entity,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.error(
                "TrashChoreManager: failed to create chore '%s': %s",
                summary,
                err,
            )

    async def async_auto_complete(self) -> None:
        """Auto-complete trash chores whose collection date has passed.

        Called from coordinator on each refresh.
        """
        if not self._tracked:
            return

        today = dt_util.now().date()
        completed_keys: list[str] = []

        for key, info in list(self._tracked.items()):
            try:
                coll_date = date_cls.fromisoformat(info["collection_date"])
            except (ValueError, TypeError):
                continue
            if coll_date >= today:
                continue  # Not yet past

            # Try to find and complete the item
            entity = info.get("todo_entity", self._trash_todo_entity)
            if not entity:
                completed_keys.append(key)
                continue

            try:
                response = await self.hass.services.async_call(
                    "todo",
                    "get_items",
                    {"status": ["needs_action"]},
                    target={"entity_id": entity},
                    blocking=True,
                    return_response=True,
                )
                if response and entity in response:
                    items = response[entity].get("items", [])
                    for item in items:
                        if item.get("summary") == info["summary"]:
                            await self.hass.services.async_call(
                                "todo",
                                "update_item",
                                {
                                    "item": item["uid"],
                                    "status": "completed",
                                },
                                target={"entity_id": entity},
                                blocking=True,
                            )
                            _LOGGER.info(
                                "TrashChoreManager: auto-completed '%s'",
                                info["summary"],
                            )
                            break
            except Exception as err:  # noqa: BLE001
                _LOGGER.error(
                    "TrashChoreManager: failed to auto-complete '%s': %s",
                    info["summary"],
                    err,
                )

            completed_keys.append(key)

        for key in completed_keys:
            self._tracked.pop(key, None)

        if completed_keys:
            await self._save()

    async def _save(self) -> None:
        """Persist tracked chores."""
        await self._store.async_save({"tracked": self._tracked})

    @staticmethod
    def _parse_date(value: str) -> date_cls:
        """Parse a date from sensor state string."""
        # Try date-only first
        try:
            return date_cls.fromisoformat(value)
        except ValueError:
            pass
        # Try full datetime
        dt = datetime.fromisoformat(value)
        return dt.date()
