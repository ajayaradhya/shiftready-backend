import logging
from enum import Enum
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages active WebSocket connections per sale event."""

    def __init__(self):
        # Using a set prevents duplicate registrations and is O(1) for removals
        self.active_connections: dict[str, set[WebSocket]] = {}

    async def connect(self, event_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        if event_id not in self.active_connections:
            self.active_connections[event_id] = set()
        self.active_connections[event_id].add(websocket)

    def disconnect(self, event_id: str, websocket: WebSocket) -> None:
        if event_id in self.active_connections:
            # discard() is safe: no KeyError if the socket was never registered
            # (e.g. connection dropped before accept completed)
            self.active_connections[event_id].discard(websocket)
            if not self.active_connections[event_id]:
                del self.active_connections[event_id]

    async def notify_event(self, event_id: str, message: dict[str, Any]) -> None:
        connections = self.active_connections.get(event_id, set())
        if not connections:
            logger.debug("No active WS connections for event %s; notification dropped.", event_id)
            return

        # Determine log display name: prefer status, then type, then generic
        display_status = message.get("status") or message.get("type") or "DATA_UPDATE"
        if isinstance(display_status, Enum):
            display_status = display_status.value

        logger.info("Broadcasting to %d WS client(s) for event %s: %s",
                    len(connections), event_id, display_status)
        for connection in connections:
            try:
                await connection.send_json(message)
            except Exception as exc:
                logger.error("Failed to send WS message to client: %s", exc)

notifier = ConnectionManager()