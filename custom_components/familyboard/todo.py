"""Todo platform for FamilyBoard CalDAV-backed task lists.

Each CalDAV calendar that contains VTODOs is exposed as a
``TodoListEntity`` with RFC 5545-compliant completion: recurring tasks
advance their DUE date instead of being marked completed.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .caldav_client import CalDAVClientManager, VTodoItem
from .const import DOMAIN, get_device_info

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up FamilyBoard CalDAV todo entities from a config entry."""
    fb: dict[str, Any] = hass.data.get(DOMAIN, {})
    managers: list[CalDAVClientManager] = fb.get("caldav_managers", [])

    entities: list[FamilyBoardCalDAVTodo] = []
    coordinator = fb.get("coordinator")

    for manager in managers:
        for cal_name in manager.calendars:
            entities.append(
                FamilyBoardCalDAVTodo(
                    manager=manager,
                    calendar_name=cal_name,
                    coordinator=coordinator,
                )
            )

    if entities:
        async_add_entities(entities)
        _LOGGER.debug("Added %d CalDAV todo entities", len(entities))


class FamilyBoardCalDAVTodo(TodoListEntity):
    """A todo list entity backed by a CalDAV calendar."""

    _attr_has_entity_name = True
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
        | TodoListEntityFeature.SET_DUE_DATE_ON_ITEM
        | TodoListEntityFeature.SET_DUE_DATETIME_ON_ITEM
        | TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM
    )

    def __init__(
        self,
        manager: CalDAVClientManager,
        calendar_name: str,
        coordinator: Any | None = None,
    ) -> None:
        """Initialize the CalDAV todo entity."""
        self._manager = manager
        self._calendar_name = calendar_name
        self._coordinator = coordinator
        self._items: list[VTodoItem] = []

        safe_name = calendar_name.lower().replace(" ", "_")
        safe_conn = manager.name.lower().replace(" ", "_")
        self._attr_unique_id = f"familyboard_caldav_{safe_conn}_{safe_name}"
        self._attr_name = f"{calendar_name}"
        self._attr_device_info = get_device_info()

    @property
    def todo_items(self) -> list[TodoItem]:
        """Return the list of todo items."""
        return [self._to_ha_item(item) for item in self._items]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose full RFC 5545 VTODO fields not covered by TodoItem."""
        items_data: list[dict[str, Any]] = []
        for item in self._items:
            data: dict[str, Any] = {
                "uid": item.uid,
                "summary": item.summary,
                "status": item.status,
            }
            if item.due is not None:
                data["due"] = item.due.isoformat()
            if item.dtstart is not None:
                data["dtstart"] = item.dtstart.isoformat()
            if item.completed is not None:
                data["completed"] = item.completed.isoformat()
            if item.description:
                data["description"] = item.description
            if item.rrule:
                data["rrule"] = item.rrule
            if item.priority is not None:
                data["priority"] = item.priority
            if item.percent_complete is not None:
                data["percent_complete"] = item.percent_complete
            if item.location:
                data["location"] = item.location
            if item.url:
                data["url"] = item.url
            if item.categories:
                data["categories"] = item.categories
            items_data.append(data)
        return {"vtodo_items": items_data}

    @staticmethod
    def _to_ha_item(item: VTodoItem) -> TodoItem:
        """Convert a VTodoItem to an HA TodoItem."""
        status = (
            TodoItemStatus.COMPLETED
            if item.status == "COMPLETED"
            else TodoItemStatus.NEEDS_ACTION
        )

        due: datetime.date | datetime.datetime | None = item.due
        # HA TodoItem expects date or datetime, not mixed
        if (
            isinstance(due, datetime.datetime)
            and due.hour == 0
            and due.minute == 0
            and due.second == 0
        ):
            due = due.date()

        return TodoItem(
            uid=item.uid,
            summary=item.summary,
            status=status,
            due=due,
            description=item.description,
        )

    async def async_update(self) -> None:
        """Fetch current todos from CalDAV."""
        try:
            self._items = await self._manager.async_get_todos(self._calendar_name)
        except Exception:
            _LOGGER.exception(
                "Failed to fetch todos from CalDAV calendar %s", self._calendar_name
            )

    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Create a new todo item."""
        await self._manager.async_add_todo(
            self._calendar_name,
            item.summary or "",
            due=item.due,
            description=item.description,
        )
        await self.async_update()
        self.async_write_ha_state()

    async def async_create_vtodo(
        self,
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
    ) -> None:
        """Create a VTODO with all RFC 5545 fields."""
        await self._manager.async_add_todo(
            self._calendar_name,
            summary,
            due=due,
            dtstart=dtstart,
            description=description,
            priority=priority,
            percent_complete=percent_complete,
            location=location,
            url=url,
            categories=categories,
        )
        await self.async_update()
        self.async_write_ha_state()

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Update an existing todo item.

        When the status changes to COMPLETED, we delegate to the manager's
        ``async_complete_todo`` which handles RRULE advancement for
        recurring tasks.
        """
        if item.uid is None:
            return

        # Check if this is a completion
        if item.status == TodoItemStatus.COMPLETED:
            # Find the current item to check if it's actually changing
            current = next((i for i in self._items if i.uid == item.uid), None)
            if current and current.status != "COMPLETED":
                await self._manager.async_complete_todo(self._calendar_name, item.uid)
                await self.async_update()
                self.async_write_ha_state()
                return

        # Regular field update
        kwargs: dict[str, Any] = {}
        if item.summary is not None:
            kwargs["summary"] = item.summary
        if item.due is not ...:  # type: ignore[comparison-overlap]
            kwargs["due"] = item.due
        if item.description is not ...:  # type: ignore[comparison-overlap]
            kwargs["description"] = item.description
        if item.status is not None:
            kwargs["status"] = (
                "COMPLETED"
                if item.status == TodoItemStatus.COMPLETED
                else "NEEDS-ACTION"
            )

        if kwargs:
            await self._manager.async_update_todo(
                self._calendar_name, item.uid, **kwargs
            )
        await self.async_update()
        self.async_write_ha_state()

    async def async_update_vtodo(
        self,
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
    ) -> None:
        """Update a VTODO with all RFC 5545 fields."""
        await self._manager.async_update_todo(
            self._calendar_name,
            uid,
            summary=summary,
            due=due,
            dtstart=dtstart,
            description=description,
            status=status,
            priority=priority,
            percent_complete=percent_complete,
            location=location,
            url=url,
            categories=categories,
        )
        await self.async_update()
        self.async_write_ha_state()

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Delete todo items by UID."""
        for uid in uids:
            await self._manager.async_delete_todo(self._calendar_name, uid)
        await self.async_update()
        self.async_write_ha_state()
