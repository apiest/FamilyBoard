"""Interactive snooze reminder engine for FamilyBoard.

Schedules notifications at the start of task-matched calendar events,
sends actionable mobile_app notifications, and handles snooze actions
with persistent state across HA restarts.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Callable

from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.event import (
    async_track_point_in_time,
    async_track_state_change_event,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    ACTION_PREFIX,
    DOMAIN,
    NOTIFICATION_TAG_PREFIX,
    SNOOZE_LARGE_STEP_MIN,
    SNOOZE_MAX_MIN,
    SNOOZE_STEP_MIN,
    STORAGE_KEY,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)

EVENT_NOTIFICATION_ACTION = "mobile_app_notification_action"

# Action ID suffixes (full ID = ACTION_PREFIX_<SUFFIX>__<uid>)
ACT_MINUS = "MINUS"
ACT_PLUS = "PLUS"
ACT_PLUS_LARGE = "PLUSLARGE"
ACT_HOME = "HOME"
ACT_CONFIRM = "CONFIRM"
ACT_DONE = "DONE"


def _short_uid(uid: str) -> str:
    """Short safe-for-tag uid suffix."""
    return "".join(c for c in (uid or "") if c.isalnum())[:24] or "x"


class ReminderManager:
    """Manages scheduled reminders, notifications and snooze actions."""

    def __init__(self, hass: HomeAssistant, members: list[dict]) -> None:
        self.hass = hass
        self.members = {m["name"]: m for m in members}
        self._store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        # uid -> state dict
        self._state: dict[str, dict[str, Any]] = {}
        # uid -> cancel callback for active timer
        self._timers: dict[str, CALLBACK_TYPE] = {}
        # uid -> cancel callback for person state listener
        self._person_listeners: dict[str, CALLBACK_TYPE] = {}
        self._action_unsub: CALLBACK_TYPE | None = None

    # ------------------------------------------------------------------ setup

    async def async_start(self) -> None:
        """Load persistent state and register event listener."""
        loaded = await self._store.async_load()
        if loaded:
            self._state = loaded.get("reminders", {})

        self._action_unsub = self.hass.bus.async_listen(
            EVENT_NOTIFICATION_ACTION, self._handle_action_event
        )

        # Re-schedule any snoozed reminders that were waiting on a timer
        now = dt_util.now()
        for uid, st in list(self._state.items()):
            if st.get("status") == "snoozed":
                target = self._parse_iso(st.get("scheduled_for"))
                if target and target > now:
                    self._schedule_timer(uid, target)
                elif target:
                    # missed during downtime — fire shortly
                    self._schedule_timer(uid, now + timedelta(seconds=10))

    async def async_stop(self) -> None:
        """Unregister listener and cancel timers."""
        if self._action_unsub:
            self._action_unsub()
            self._action_unsub = None
        for cancel in list(self._timers.values()):
            cancel()
        self._timers.clear()
        for cancel in list(self._person_listeners.values()):
            cancel()
        self._person_listeners.clear()

    # --------------------------------------------------------- public sync API

    @callback
    def sync_from_chores(self, chores: list[dict]) -> None:
        """Schedule reminders for chores that have a start time.

        Called from coordinator after each refresh.
        """
        seen_uids: set[str] = set()
        now = dt_util.now()

        for chore in chores:
            uid = chore.get("uid")
            start_str = chore.get("start")
            member = chore.get("member")
            if not uid or not start_str:
                continue
            member_conf = self.members.get(member) if member else None
            if not member_conf or not member_conf.get("notify"):
                continue

            seen_uids.add(uid)
            start = self._parse_iso(start_str)
            if not start:
                continue

            existing = self._state.get(uid)
            if existing and existing.get("status") in ("snoozed", "done"):
                continue
            if existing and existing.get("status") == "armed":
                # Already scheduled for this start
                if existing.get("scheduled_for") == start.isoformat():
                    continue
                # Start time changed — reschedule
                self._cancel_timer(uid)

            if start <= now:
                # Missed — fire immediately (only if recent, within 1 hour)
                if (now - start) < timedelta(hours=1):
                    self.hass.async_create_task(self._fire_reminder(uid, chore))
                continue

            self._state[uid] = {
                "uid": uid,
                "summary": chore.get("summary", ""),
                "member": member,
                "notify_target": member_conf["notify"],
                "todo_entity": chore.get("todo_entity"),
                "person_entity": member_conf.get("person"),
                "color": chore.get("color"),
                "original_start": start.isoformat(),
                "scheduled_for": start.isoformat(),
                "snooze_offset_min": 0,
                "status": "armed",
            }
            self._schedule_timer(uid, start)

        # Cleanup stale entries (chore removed/completed externally)
        for uid in list(self._state.keys()):
            st = self._state[uid]
            if st.get("status") in ("armed", "snoozed") and uid not in seen_uids:
                self._cancel_timer(uid)
                self._cancel_person_listener(uid)
                self._state.pop(uid, None)

        self.hass.async_create_task(self._async_save())

    # ----------------------------------------------------------- timer helpers

    def _schedule_timer(self, uid: str, when: datetime) -> None:
        self._cancel_timer(uid)

        @callback
        def _fire(_now: datetime) -> None:
            self._timers.pop(uid, None)
            self.hass.async_create_task(self._fire_reminder(uid))

        self._timers[uid] = async_track_point_in_time(self.hass, _fire, when)

    def _cancel_timer(self, uid: str) -> None:
        cancel = self._timers.pop(uid, None)
        if cancel:
            cancel()

    def _cancel_person_listener(self, uid: str) -> None:
        cancel = self._person_listeners.pop(uid, None)
        if cancel:
            cancel()

    # ------------------------------------------------------- notification core

    async def _fire_reminder(
        self, uid: str, task: dict | None = None
    ) -> None:
        """Send the initial reminder notification (offset reset to 0)."""
        st = self._state.get(uid)
        if not st and task:
            # Bootstrap state from task (immediate fire path)
            member = task.get("member")
            member_conf = self.members.get(member) if member else None
            if not member_conf or not member_conf.get("notify"):
                return
            st = {
                "uid": uid,
                "summary": task.get("summary", ""),
                "member": member,
                "notify_target": member_conf["notify"],
                "todo_entity": task.get("todo_entity"),
                "person_entity": member_conf.get("person"),
                "color": task.get("color"),
                "original_start": task.get("start"),
                "scheduled_for": None,
                "snooze_offset_min": 0,
                "status": "armed",
            }
            self._state[uid] = st
        if not st:
            return

        st["snooze_offset_min"] = 0
        st["status"] = "active"
        st["scheduled_for"] = None
        await self._push_notification(uid)
        await self._async_save()

    async def _push_notification(self, uid: str) -> None:
        """Send (or update) the actionable notification for this uid."""
        st = self._state.get(uid)
        if not st:
            return
        target = st.get("notify_target")
        if not target:
            return

        offset = int(st.get("snooze_offset_min", 0))
        summary = st.get("summary", "Taak")
        tag = NOTIFICATION_TAG_PREFIX + _short_uid(uid)

        if offset == 0:
            now = dt_util.now()
            body = f"⏰ {now.strftime('%H:%M')} — wat doe je hiermee?"
        else:
            target_time = dt_util.now() + timedelta(minutes=offset)
            body = (
                f"💤 Sluimer +{offset} min — herinnering om "
                f"{target_time.strftime('%H:%M')}"
            )

        actions: list[dict] = []
        person_entity = st.get("person_entity")
        person_away = False
        if person_entity:
            ps = self.hass.states.get(person_entity)
            if ps and ps.state and ps.state != "home":
                person_away = True

        if offset == 0:
            # Initial: snooze options + done
            actions.append(
                {"action": self._action_id(ACT_PLUS, uid), "title": f"+{SNOOZE_STEP_MIN}m"}
            )
            if person_away:
                actions.append(
                    {"action": self._action_id(ACT_HOME, uid), "title": "🏠 Thuis"}
                )
            else:
                actions.append(
                    {"action": self._action_id(ACT_PLUS_LARGE, uid), "title": f"+{SNOOZE_LARGE_STEP_MIN}m"}
                )
            actions.append(
                {"action": self._action_id(ACT_DONE, uid), "title": "✓ Klaar"}
            )
        else:
            # Snoozing: ±15 + confirm (Done bereikbaar via opnieuw +15→0 of via taakkaart)
            actions.append(
                {"action": self._action_id(ACT_MINUS, uid), "title": f"−{SNOOZE_STEP_MIN}m"}
            )
            actions.append(
                {"action": self._action_id(ACT_PLUS, uid), "title": f"+{SNOOZE_STEP_MIN}m"}
            )
            actions.append(
                {"action": self._action_id(ACT_CONFIRM, uid), "title": "✅ Bevestig"}
            )

        try:
            await self.hass.services.async_call(
                "notify",
                target,
                {
                    "title": summary,
                    "message": body,
                    "data": {
                        "tag": tag,
                        "actions": actions,
                        "channel": "FamilyBoard Reminders",
                        "importance": "high",
                        "persistent": True,
                        "sticky": True,
                    },
                },
                blocking=False,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("FamilyBoard: notify.%s failed for %s: %s", target, uid, err)

    async def _clear_notification(self, uid: str) -> None:
        st = self._state.get(uid)
        if not st:
            return
        target = st.get("notify_target")
        if not target:
            return
        tag = NOTIFICATION_TAG_PREFIX + _short_uid(uid)
        try:
            await self.hass.services.async_call(
                "notify",
                target,
                {"message": "clear_notification", "data": {"tag": tag}},
                blocking=False,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("FamilyBoard: clear notification failed for %s: %s", uid, err)

    @staticmethod
    def _action_id(action: str, uid: str) -> str:
        return f"{ACTION_PREFIX}_{action}__{uid}"

    # --------------------------------------------------------- event handling

    @callback
    def _handle_action_event(self, event: Event) -> None:
        action = event.data.get("action", "")
        if not action.startswith(ACTION_PREFIX + "_"):
            return
        try:
            rest = action[len(ACTION_PREFIX) + 1:]
            act_name, uid = rest.split("__", 1)
        except ValueError:
            return
        self.hass.async_create_task(self._dispatch_action(act_name, uid))

    async def _dispatch_action(self, act_name: str, uid: str) -> None:
        st = self._state.get(uid)
        if not st:
            _LOGGER.debug("FamilyBoard: action %s for unknown uid %s", act_name, uid)
            return

        offset = int(st.get("snooze_offset_min", 0))

        if act_name == ACT_MINUS:
            st["snooze_offset_min"] = max(0, offset - SNOOZE_STEP_MIN)
            await self._push_notification(uid)
        elif act_name == ACT_PLUS:
            st["snooze_offset_min"] = min(SNOOZE_MAX_MIN, offset + SNOOZE_STEP_MIN)
            await self._push_notification(uid)
        elif act_name == ACT_PLUS_LARGE:
            st["snooze_offset_min"] = min(SNOOZE_MAX_MIN, offset + SNOOZE_LARGE_STEP_MIN)
            await self._push_notification(uid)
        elif act_name == ACT_CONFIRM:
            await self._confirm_snooze(uid)
        elif act_name == ACT_HOME:
            await self._wait_for_home(uid)
        elif act_name == ACT_DONE:
            await self._complete_task(uid)

        await self._async_save()

    async def _confirm_snooze(self, uid: str) -> None:
        st = self._state.get(uid)
        if not st:
            return
        offset = int(st.get("snooze_offset_min", 0))
        await self._clear_notification(uid)
        if offset <= 0:
            # Confirm with 0 = nothing to do, just dismiss
            st["status"] = "dismissed"
            return
        when = dt_util.now() + timedelta(minutes=offset)
        st["status"] = "snoozed"
        st["scheduled_for"] = when.isoformat()
        self._schedule_timer(uid, when)

    async def _wait_for_home(self, uid: str) -> None:
        st = self._state.get(uid)
        if not st:
            return
        person_entity = st.get("person_entity")
        if not person_entity:
            return
        await self._clear_notification(uid)
        st["status"] = "waiting_home"
        st["scheduled_for"] = None

        @callback
        def _on_change(event: Event) -> None:
            new_state = event.data.get("new_state")
            if new_state and new_state.state == "home":
                cancel = self._person_listeners.pop(uid, None)
                if cancel:
                    cancel()
                self.hass.async_create_task(self._fire_reminder(uid))

        self._cancel_person_listener(uid)
        self._person_listeners[uid] = async_track_state_change_event(
            self.hass, [person_entity], _on_change
        )

    async def _complete_task(self, uid: str) -> None:
        st = self._state.get(uid)
        if not st:
            return
        todo_entity = st.get("todo_entity")
        await self._clear_notification(uid)
        if todo_entity and uid:
            try:
                await self.hass.services.async_call(
                    "todo",
                    "update_item",
                    {"item": uid, "status": "completed"},
                    target={"entity_id": todo_entity},
                    blocking=True,
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.error(
                    "FamilyBoard: todo.update_item failed for %s: %s", uid, err
                )
        st["status"] = "done"
        self._cancel_timer(uid)
        self._cancel_person_listener(uid)

    # --------------------------------------------------------- helper services

    async def async_test_fire(self, uid: str) -> None:
        """Force-fire the reminder for a given uid (for testing)."""
        await self._fire_reminder(uid)

    async def async_cancel(self, uid: str) -> None:
        """Cancel an active reminder."""
        await self._clear_notification(uid)
        self._cancel_timer(uid)
        self._cancel_person_listener(uid)
        self._state.pop(uid, None)
        await self._async_save()

    # --------------------------------------------------------------- internals

    async def _async_save(self) -> None:
        await self._store.async_save({"reminders": self._state})

    @staticmethod
    def _parse_iso(value: Any) -> datetime | None:
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
        return dt
