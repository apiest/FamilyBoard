"""CalDAV client manager for FamilyBoard.

Owns the CalDAV connection lifecycle and exposes RFC 5545-compliant VTODO
operations. Recurring tasks are advanced (DUE updated to the next occurrence)
instead of being marked completed, preserving the recurrence chain.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
import datetime
import logging
from typing import Any

import caldav
from caldav.lib.error import NotFoundError
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from vobject.base import Component as VObject

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = "familyboard_caldav_sync"
STORAGE_VERSION = 1


@dataclass
class VTodoItem:
    """Parsed VTODO — all RFC 5545 fields preserved."""

    uid: str
    summary: str
    status: str
    due: datetime.datetime | datetime.date | None = None
    dtstart: datetime.datetime | datetime.date | None = None
    completed: datetime.datetime | None = None
    description: str | None = None
    rrule: str | None = None
    calendar_name: str = ""
    calendar_url: str = ""
    priority: int | None = None
    percent_complete: int | None = None
    location: str | None = None
    url: str | None = None
    categories: list[str] = field(default_factory=list)

    @property
    def is_recurring(self) -> bool:
        """Return True if this VTODO has a recurrence rule."""
        return self.rrule is not None


def _parse_vtodo(todo: caldav.Todo, calendar_name: str = "") -> VTodoItem:
    """Parse a caldav.Todo into a VTodoItem."""
    vobj: VObject = todo.vobject_instance
    vtodo = vobj.vtodo

    uid = str(vtodo.uid.value) if hasattr(vtodo, "uid") else ""
    summary = str(vtodo.summary.value) if hasattr(vtodo, "summary") else ""
    status_raw = str(vtodo.status.value) if hasattr(vtodo, "status") else "NEEDS-ACTION"
    description = (
        str(vtodo.description.value) if hasattr(vtodo, "description") else None
    )

    due: datetime.datetime | datetime.date | None = None
    if hasattr(vtodo, "due"):
        due = vtodo.due.value

    rrule: str | None = None
    if hasattr(vtodo, "rrule"):
        rrule = str(vtodo.rrule.value)

    priority: int | None = None
    if hasattr(vtodo, "priority"):
        with contextlib.suppress(ValueError, TypeError):
            priority = int(vtodo.priority.value)

    categories: list[str] = []
    if hasattr(vtodo, "categories"):
        cats = vtodo.categories.value
        categories = [str(c) for c in cats] if isinstance(cats, list) else [str(cats)]

    dtstart: datetime.datetime | datetime.date | None = None
    if hasattr(vtodo, "dtstart"):
        dtstart = vtodo.dtstart.value

    completed_dt: datetime.datetime | None = None
    if hasattr(vtodo, "completed"):
        val = vtodo.completed.value
        if isinstance(val, datetime.datetime):
            completed_dt = val

    percent_complete: int | None = None
    if hasattr(vtodo, "percent_complete"):
        with contextlib.suppress(ValueError, TypeError):
            percent_complete = int(vtodo.percent_complete.value)

    location: str | None = None
    if hasattr(vtodo, "location"):
        location = str(vtodo.location.value) or None

    vtodo_url: str | None = None
    if hasattr(vtodo, "url"):
        vtodo_url = str(vtodo.url.value) or None

    return VTodoItem(
        uid=uid,
        summary=summary,
        status=status_raw.upper(),
        due=due,
        dtstart=dtstart,
        completed=completed_dt,
        description=description,
        rrule=rrule,
        calendar_name=calendar_name,
        calendar_url=str(todo.url) if todo.url else "",
        priority=priority,
        percent_complete=percent_complete,
        location=location,
        url=vtodo_url,
        categories=categories,
    )


def _advance_rrule(vtodo_vobj: VObject) -> bool:
    """Advance the DUE date of a recurring VTODO to the next occurrence.

    Returns True if the task was advanced (still has future occurrences),
    False if the recurrence is exhausted.
    """
    vtodo = vtodo_vobj.vtodo

    if not hasattr(vtodo, "rrule"):
        return False

    rruleset = vtodo.getrruleset()
    if rruleset is None:
        return False

    current_due: datetime.datetime | datetime.date | None = None
    if hasattr(vtodo, "due"):
        current_due = vtodo.due.value

    if current_due is None:
        # No DUE date — use DTSTART as anchor
        if hasattr(vtodo, "dtstart"):
            current_due = vtodo.dtstart.value
        else:
            _LOGGER.warning("Recurring VTODO has no DUE or DTSTART, cannot advance")
            return False

    # Ensure we have a datetime for rruleset.after().
    # Keep timezone awareness consistent with what the rruleset produces:
    # date-only VTODOs → naive datetimes; tz-aware VTODOs → aware datetimes.
    if isinstance(current_due, datetime.date) and not isinstance(
        current_due, datetime.datetime
    ):
        current_due_dt = datetime.datetime.combine(current_due, datetime.time.min)
    else:
        current_due_dt = current_due
        if current_due_dt.tzinfo is None:
            current_due_dt = current_due_dt.replace(tzinfo=datetime.UTC)

    next_due = rruleset.after(current_due_dt)
    if next_due is None:
        # Recurrence exhausted
        return False

    # Advance DUE to next occurrence
    if hasattr(vtodo, "due"):
        if isinstance(vtodo.due.value, datetime.date) and not isinstance(
            vtodo.due.value, datetime.datetime
        ):
            # Preserve date-only DUE
            vtodo.due.value = (
                next_due.date() if isinstance(next_due, datetime.datetime) else next_due
            )
        else:
            vtodo.due.value = next_due
    else:
        vtodo.add("due").value = next_due

    # Reset STATUS to NEEDS-ACTION
    vtodo.status.value = "NEEDS-ACTION"

    # Remove COMPLETED timestamp if present
    if hasattr(vtodo, "completed"):
        vtodo.contents.pop("completed", None)

    # Do NOT update DTSTART — it anchors the RRULE. Shifting it would
    # reset COUNT / make UNTIL unreachable. Only DUE advances.

    return True


class CalDAVClientManager:
    """Manage a CalDAV connection and provide VTODO operations."""

    def __init__(
        self,
        hass: HomeAssistant,
        config: dict[str, Any],
    ) -> None:
        """Initialize the CalDAV client manager."""
        self._hass = hass
        self._url: str = config["url"]
        self._username: str = config["username"]
        self._password: str = config["password"]
        self._verify_ssl: bool = config.get("verify_ssl", True)
        self._name: str = config.get("name") or self._url
        self._server_handles_rrule: bool = config.get("server_handles_rrule", False)
        self._client: caldav.DAVClient | None = None
        self._calendars: dict[str, caldav.Calendar] = {}
        self._store = Store[dict[str, Any]](hass, STORAGE_VERSION, STORAGE_KEY)
        self._started = False

    @property
    def name(self) -> str:
        """Return the connection name."""
        return self._name

    @property
    def calendars(self) -> dict[str, caldav.Calendar]:
        """Return discovered calendars keyed by name."""
        return self._calendars

    async def async_start(self) -> None:
        """Connect to the CalDAV server and discover calendars."""
        if self._started:
            return

        try:
            self._client = await self._hass.async_add_executor_job(self._connect)
            cals = await self._hass.async_add_executor_job(self._discover_calendars)
            self._calendars = {cal.name: cal for cal in cals if cal.name}
            self._started = True
            _LOGGER.info(
                "CalDAV connected to %s, found %d calendar(s): %s",
                self._url,
                len(self._calendars),
                ", ".join(self._calendars.keys()),
            )
        except Exception:
            _LOGGER.exception("Failed to connect to CalDAV server %s", self._url)
            raise

    def _connect(self) -> caldav.DAVClient:
        """Create and return a DAVClient (sync, runs in executor)."""
        return caldav.DAVClient(
            url=self._url,
            username=self._username,
            password=self._password,
            ssl_verify_cert=self._verify_ssl,
        )

    def _discover_calendars(self) -> list[caldav.Calendar]:
        """Discover calendars from the principal (sync, runs in executor)."""
        if self._client is None:
            return []
        principal = self._client.principal()
        return principal.calendars()

    async def async_stop(self) -> None:
        """Clean up the client connection."""
        self._client = None
        self._calendars = {}
        self._started = False

    async def async_get_todos(
        self,
        calendar_name: str,
        *,
        include_completed: bool = False,
    ) -> list[VTodoItem]:
        """Return VTODOs from a specific calendar."""
        cal = self._calendars.get(calendar_name)
        if cal is None:
            _LOGGER.warning(
                "Calendar '%s' not found in CalDAV connection", calendar_name
            )
            return []

        raw_todos: list[caldav.Todo] = await self._hass.async_add_executor_job(
            self._search_todos, cal, include_completed
        )
        return [_parse_vtodo(t, calendar_name) for t in raw_todos]

    @staticmethod
    def _search_todos(
        cal: caldav.Calendar, include_completed: bool
    ) -> list[caldav.Todo]:
        """Search for todos in a calendar (sync, runs in executor)."""
        return cal.search(todo=True, include_completed=include_completed)

    async def async_complete_todo(
        self, calendar_name: str, uid: str
    ) -> VTodoItem | None:
        """Complete a VTODO. Recurring tasks are advanced, not completed.

        Returns the updated VTodoItem, or None if the task was not found.
        """
        cal = self._calendars.get(calendar_name)
        if cal is None:
            return None

        todo = await self._hass.async_add_executor_job(self._find_todo_by_uid, cal, uid)
        if todo is None:
            _LOGGER.warning("VTODO %s not found in calendar %s", uid, calendar_name)
            return None

        updated = await self._hass.async_add_executor_job(
            self._complete_or_advance,
            todo,
            calendar_name,
            self._server_handles_rrule,
        )
        return updated

    @staticmethod
    def _find_todo_by_uid(cal: caldav.Calendar, uid: str) -> caldav.Todo | None:
        """Find a VTODO by UID (sync, runs in executor)."""
        try:
            return cal.todo_by_uid(uid)
        except NotFoundError:
            return None
        except Exception:
            _LOGGER.exception("Error finding VTODO %s", uid)
            return None

    @staticmethod
    def _complete_or_advance(
        todo: caldav.Todo,
        calendar_name: str,
        server_handles_rrule: bool = False,
    ) -> VTodoItem:
        """Complete or advance a VTODO (sync, runs in executor).

        When *server_handles_rrule* is True, recurring tasks are simply
        marked COMPLETED and the server is expected to create the next
        occurrence. When False (the default), the client advances DUE
        to the next RRULE occurrence itself.
        """
        vobj = todo.vobject_instance

        if not server_handles_rrule and _advance_rrule(vobj):
            # Client-side recurrence: save the advanced VTODO
            todo.save(no_create=True)
            _LOGGER.debug(
                "Advanced recurring VTODO %s to next occurrence",
                vobj.vtodo.uid.value,
            )
        else:
            # Non-recurring, exhausted, or server handles RRULE: mark completed
            vobj.vtodo.status.value = "COMPLETED"
            if not hasattr(vobj.vtodo, "completed"):
                vobj.vtodo.add("completed")
            vobj.vtodo.completed.value = datetime.datetime.now(datetime.UTC)
            todo.save(no_create=True)
            _LOGGER.debug("Completed VTODO %s", vobj.vtodo.uid.value)

        return _parse_vtodo(todo, calendar_name)

    async def async_add_todo(
        self,
        calendar_name: str,
        summary: str,
        *,
        due: datetime.datetime | datetime.date | None = None,
        dtstart: datetime.datetime | datetime.date | None = None,
        description: str | None = None,
        priority: int | None = None,
        percent_complete: int | None = None,
        location: str | None = None,
        url: str | None = None,
        categories: list[str] | None = None,
    ) -> VTodoItem | None:
        """Create a new VTODO in the specified calendar."""
        cal = self._calendars.get(calendar_name)
        if cal is None:
            return None

        todo = await self._hass.async_add_executor_job(
            self._create_todo,
            cal,
            summary,
            due,
            dtstart,
            description,
            priority,
            percent_complete,
            location,
            url,
            categories,
        )
        return _parse_vtodo(todo, calendar_name) if todo else None

    @staticmethod
    def _create_todo(
        cal: caldav.Calendar,
        summary: str,
        due: datetime.datetime | datetime.date | None,
        dtstart: datetime.datetime | datetime.date | None,
        description: str | None,
        priority: int | None,
        percent_complete: int | None,
        location: str | None,
        url: str | None,
        categories: list[str] | None,
    ) -> caldav.Todo | None:
        """Create a VTODO (sync, runs in executor)."""
        kwargs: dict[str, Any] = {"summary": summary}
        if due is not None:
            kwargs["due"] = due
        if dtstart is not None:
            kwargs["dtstart"] = dtstart
        if description:
            kwargs["description"] = description
        if priority is not None:
            kwargs["priority"] = priority
        # Fields not supported by caldav.add_todo() — set via vobject after creation
        extra_fields: dict[str, Any] = {}
        if percent_complete is not None:
            extra_fields["percent-complete"] = str(percent_complete)
        if location:
            extra_fields["location"] = location
        if url:
            extra_fields["url"] = url
        if categories:
            extra_fields["categories"] = categories
        try:
            todo = cal.add_todo(**kwargs)
            if extra_fields and todo is not None:
                vtodo = todo.vobject_instance.vtodo
                for prop, val in extra_fields.items():
                    vtodo.add(prop).value = val
                todo.save(no_create=True)
        except Exception:
            _LOGGER.exception("Failed to create VTODO '%s'", summary)
            return None
        else:
            return todo

    async def async_update_todo(
        self,
        calendar_name: str,
        uid: str,
        *,
        summary: str | None = None,
        due: datetime.datetime | datetime.date | None = ...,  # type: ignore[assignment]
        dtstart: datetime.datetime | datetime.date | None = ...,  # type: ignore[assignment]
        description: str | None = ...,  # type: ignore[assignment]
        status: str | None = None,
        priority: int | None = ...,  # type: ignore[assignment]
        percent_complete: int | None = ...,  # type: ignore[assignment]
        location: str | None = ...,  # type: ignore[assignment]
        url: str | None = ...,  # type: ignore[assignment]
        categories: list[str] | None = ...,  # type: ignore[assignment]
    ) -> VTodoItem | None:
        """Update fields on an existing VTODO."""
        cal = self._calendars.get(calendar_name)
        if cal is None:
            return None

        todo = await self._hass.async_add_executor_job(self._find_todo_by_uid, cal, uid)
        if todo is None:
            return None

        fields: dict[str, Any] = {
            "summary": summary,
            "due": due,
            "dtstart": dtstart,
            "description": description,
            "status": status,
            "priority": priority,
            "percent_complete": percent_complete,
            "location": location,
            "url": url,
            "categories": categories,
        }
        updated = await self._hass.async_add_executor_job(
            self._update_fields, todo, calendar_name, fields
        )
        return updated

    @staticmethod
    def _set_or_remove(vtodo: Any, prop: str, value: Any, sentinel: Any = ...) -> None:
        """Set, remove, or skip a vobject property."""
        if value is sentinel:
            return  # not provided
        if value is None:
            if hasattr(vtodo, prop):
                vtodo.contents.pop(prop, None)
        elif hasattr(vtodo, prop):
            getattr(vtodo, prop).value = value
        else:
            vtodo.add(prop).value = value

    @staticmethod
    def _update_fields(
        todo: caldav.Todo,
        calendar_name: str,
        fields: dict[str, Any],
    ) -> VTodoItem:
        """Mutate VTODO fields and save (sync, runs in executor)."""
        vtodo = todo.vobject_instance.vtodo
        _set = CalDAVClientManager._set_or_remove

        if fields["summary"] is not None:
            vtodo.summary.value = fields["summary"]

        _set(vtodo, "due", fields["due"])
        _set(vtodo, "dtstart", fields["dtstart"])
        _set(vtodo, "description", fields["description"])
        _set(vtodo, "location", fields["location"])
        _set(vtodo, "url", fields["url"])

        if fields["status"] is not None:
            vtodo.status.value = fields["status"]

        # Integer fields: convert to string for vobject
        priority = fields["priority"]
        if priority is not ...:
            if priority is None:
                if hasattr(vtodo, "priority"):
                    vtodo.contents.pop("priority", None)
            else:
                if hasattr(vtodo, "priority"):
                    vtodo.priority.value = str(priority)
                else:
                    vtodo.add("priority").value = str(priority)

        pct = fields["percent_complete"]
        if pct is not ...:
            prop = "percent-complete"
            if pct is None:
                if hasattr(vtodo, "percent_complete"):
                    vtodo.contents.pop(prop, None)
            else:
                if prop in vtodo.contents:
                    vtodo.contents[prop][0].value = str(pct)
                else:
                    vtodo.add(prop).value = str(pct)

        cats = fields["categories"]
        if cats is not ...:
            if cats is None:
                vtodo.contents.pop("categories", None)
            else:
                vtodo.contents.pop("categories", None)
                vtodo.add("categories").value = cats

        todo.save(no_create=True)
        return _parse_vtodo(todo, calendar_name)

    async def async_delete_todo(self, calendar_name: str, uid: str) -> bool:
        """Delete a VTODO by UID. Returns True on success."""
        cal = self._calendars.get(calendar_name)
        if cal is None:
            return False

        todo = await self._hass.async_add_executor_job(self._find_todo_by_uid, cal, uid)
        if todo is None:
            return False

        try:
            await self._hass.async_add_executor_job(todo.delete)
        except Exception:
            _LOGGER.exception("Failed to delete VTODO %s", uid)
            return False
        else:
            return True
