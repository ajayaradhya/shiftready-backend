from fastapi import WebSocket
from typing import Dict, Set, Any
from enum import Enum
import logging

logger = logging.getLogger(__name__)

class ConnectionManager:
    def __init__(self):
        # Using a Set prevents duplicate registrations and is faster for removals
        self.active_connections: Dict[str, Set[WebSocket]] = {}

    async def connect(self, event_id: str, websocket: WebSocket):
        await websocket.accept()
        if event_id not in self.active_connections:
            self.active_connections[event_id] = set()
        self.active_connections[event_id].add(websocket)

    def disconnect(self, event_id: str, websocket: WebSocket):
        if event_id in self.active_connections:
            self.active_connections[event_id].remove(websocket)
            if not self.active_connections[event_id]:
                del self.active_connections[event_id]

    async def notify_event(self, event_id: str, message: Dict[str, Any]):
        connections = self.active_connections.get(event_id, set())
        if not connections:
            logger.info(f"📡 No active WS connections for event {event_id}. Notification dropped.")
            return

        # Determine log display name: prioritize status, then type, then generic
        display_status = message.get("status") or message.get("type") or "DATA_UPDATE"
        if isinstance(display_status, Enum):
            display_status = display_status.value

        logger.info(f"📡 Broadcasting to {len(connections)} clients for event {event_id}: {display_status}")
        for connection in connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"❌ Failed to send WS message: {e}")

notifier = ConnectionManager()