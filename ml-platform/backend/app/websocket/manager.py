from fastapi import WebSocket
from typing import Any
import json


class ConnectionManager:
    def __init__(self):
        self._connections: dict[str, list[WebSocket]] = {}

    async def connect(self, run_id: str, websocket: WebSocket):
        await websocket.accept()
        if run_id not in self._connections:
            self._connections[run_id] = []
        self._connections[run_id].append(websocket)

    def disconnect(self, run_id: str, websocket: WebSocket):
        if run_id in self._connections:
            try:
                self._connections[run_id].remove(websocket)
            except ValueError:
                pass
            if not self._connections[run_id]:
                del self._connections[run_id]

    async def broadcast(self, run_id: str, message: dict[str, Any]):
        if run_id not in self._connections:
            return
        disconnected = []
        for ws in self._connections[run_id]:
            try:
                await ws.send_json(message)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            self.disconnect(run_id, ws)


manager = ConnectionManager()
