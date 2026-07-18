from fastapi import WebSocket
from typing import Dict, List
import json


class ConnectionManager:
    def __init__(self):
        # machine_id -> lista de conexões
        self._connections: Dict[int, List[WebSocket]] = {}
        # user_id -> lista de conexões (para atualizações gerais)
        self._user_connections: Dict[int, List[WebSocket]] = {}

    async def connect_machine(self, websocket: WebSocket, machine_id: int):
        await websocket.accept()
        self._connections.setdefault(machine_id, []).append(websocket)

    async def connect_user(self, websocket: WebSocket, user_id: int):
        await websocket.accept()
        self._user_connections.setdefault(user_id, []).append(websocket)

    def disconnect_machine(self, websocket: WebSocket, machine_id: int):
        conns = self._connections.get(machine_id, [])
        if websocket in conns:
            conns.remove(websocket)

    def disconnect_user(self, websocket: WebSocket, user_id: int):
        conns = self._user_connections.get(user_id, [])
        if websocket in conns:
            conns.remove(websocket)

    async def broadcast_metric(self, machine_id: int, data: dict):
        await self._broadcast(self._connections.get(machine_id, []), {"type": "metric", "data": data})

    async def broadcast_anomaly(self, machine_id: int, owner_id: int, data: dict):
        await self._broadcast(self._connections.get(machine_id, []), {"type": "anomaly", "data": data})
        await self._broadcast(self._user_connections.get(owner_id, []), {"type": "anomaly", "data": data})

    async def _broadcast(self, connections: List[WebSocket], payload: dict):
        dead = []
        for ws in connections:
            try:
                await ws.send_text(json.dumps(payload, default=str))
            except Exception:
                dead.append(ws)
        for ws in dead:
            if ws in connections:
                connections.remove(ws)


manager = ConnectionManager()
