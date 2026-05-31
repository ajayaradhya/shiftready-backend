import logging
from enum import Enum
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages active WebSocket connections per sale event and per user."""

    def __init__(self):
        self.active_connections: dict[str, set[WebSocket]] = {}
        self.user_connections: dict[str, set[WebSocket]] = {}

    # ── sale event WS ─────────────────────────────────────────────────────────

    async def connect(self, event_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        if event_id not in self.active_connections:
            self.active_connections[event_id] = set()
        self.active_connections[event_id].add(websocket)

    def disconnect(self, event_id: str, websocket: WebSocket) -> None:
        if event_id in self.active_connections:
            self.active_connections[event_id].discard(websocket)
            if not self.active_connections[event_id]:
                del self.active_connections[event_id]

    async def notify_event(self, event_id: str, message: dict[str, Any]) -> None:
        connections = self.active_connections.get(event_id, set()).copy()
        if not connections:
            logger.debug(
                "No active WS connections for event %s; notification dropped.", event_id
            )
            return

        display_status = message.get("status") or message.get("type") or "DATA_UPDATE"
        if isinstance(display_status, Enum):
            display_status = display_status.value

        logger.info(
            "Broadcasting to %d WS client(s) for event %s: %s",
            len(connections),
            event_id,
            display_status,
        )
        dead: set[WebSocket] = set()
        for connection in connections:
            try:
                await connection.send_json(message)
            except Exception as exc:
                logger.error("Failed to send WS message to client: %s", exc)
                dead.add(connection)
        if dead:
            self.active_connections.get(event_id, set()).difference_update(dead)
            if not self.active_connections.get(event_id):
                self.active_connections.pop(event_id, None)

    # ── user-level WS (messaging) ─────────────────────────────────────────────

    async def connect_user(self, uid: str, websocket: WebSocket) -> None:
        await websocket.accept()
        if uid not in self.user_connections:
            self.user_connections[uid] = set()
        self.user_connections[uid].add(websocket)

    def disconnect_user(self, uid: str, websocket: WebSocket) -> None:
        if uid in self.user_connections:
            self.user_connections[uid].discard(websocket)
            if not self.user_connections[uid]:
                del self.user_connections[uid]

    async def notify_user(self, uid: str, message: dict[str, Any]) -> None:
        connections = self.user_connections.get(uid, set()).copy()
        if not connections:
            logger.debug(
                "No active user WS connections for uid %s; notification dropped.", uid
            )
            return
        logger.info("Notifying uid %s via %d WS connection(s)", uid, len(connections))
        dead: set[WebSocket] = set()
        for connection in connections:
            try:
                await connection.send_json(message)
            except Exception as exc:
                logger.error("Failed to send user WS message: %s", exc)
                dead.add(connection)
        if dead:
            self.user_connections.get(uid, set()).difference_update(dead)
            if not self.user_connections.get(uid):
                self.user_connections.pop(uid, None)


notifier = ConnectionManager()
