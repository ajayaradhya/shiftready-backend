from fastapi import WebSocket
from typing import Dict, List
import logging

logger = logging.getLogger(__name__)

class ConnectionManager:
    def __init__(self):
        # Maps event_id -> List of active WebSockets
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, event_id: str, websocket: WebSocket):
        await websocket.accept()
        if event_id not in self.active_connections:
            self.active_connections[event_id] = []
        self.active_connections[event_id].append(websocket)

    def disconnect(self, event_id: str, websocket: WebSocket):
        if event_id in self.active_connections:
            self.active_connections[event_id].remove(websocket)

    async def notify_event(self, event_id: str, message: dict):
        connections = self.active_connections.get(event_id, [])
        if not connections:
            logger.info(f"📡 No active WS connections for event {event_id}. Notification dropped.")
            return

        logger.info(f"📡 Broadcasting to {len(connections)} clients for event {event_id}: {message.get('status')}")
        for connection in connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"❌ Failed to send WS message: {e}")

notifier = ConnectionManager()