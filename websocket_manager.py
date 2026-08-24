from typing import Dict, List
from fastapi import WebSocket

class ConnectionManager:
    def __init__(self):
        # Maps event_id (int) to a list of active WebSocket connections
        self.active_connections: Dict[int, List[WebSocket]] = {}

    async def connect(self, event_id: int, websocket: WebSocket):
        await websocket.accept()
        if event_id not in self.active_connections:
            self.active_connections[event_id] = []
        self.active_connections[event_id].append(websocket)

    def disconnect(self, event_id: int, websocket: WebSocket):
        if event_id in self.active_connections:
            if websocket in self.active_connections[event_id]:
                self.active_connections[event_id].remove(websocket)
            if not self.active_connections[event_id]:
                del self.active_connections[event_id]

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        await websocket.send_json(message)

    async def broadcast_event_update(self, event_id: int, message: dict):
        if event_id in self.active_connections:
            for connection in self.active_connections[event_id]:
                try:
                    await connection.send_json(message)
                except Exception:
                    # Connection might be closed, handle it during disconnect
                    pass

# Singleton manager instance
manager = ConnectionManager()
