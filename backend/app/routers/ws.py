from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from app.core.websocket import manager
from app.core.security import decode_token
from app.database import SessionLocal
from app.models.machine import Machine

router = APIRouter()


def _get_user_id(token: str):
    payload = decode_token(token)
    if not payload:
        return None
    return int(payload.get("sub", 0))


@router.websocket("/ws/machine/{machine_id}")
async def ws_machine(websocket: WebSocket, machine_id: int, token: str = Query(...)):
    user_id = _get_user_id(token)
    if not user_id:
        await websocket.close(code=4001)
        return

    db = SessionLocal()
    try:
        machine = db.query(Machine).filter(Machine.id == machine_id, Machine.owner_id == user_id).first()
        if not machine:
            await websocket.close(code=4004)
            return
    finally:
        db.close()

    await manager.connect_machine(websocket, machine_id)
    try:
        while True:
            await websocket.receive_text()  # mantém conexão viva (ping do cliente)
    except WebSocketDisconnect:
        manager.disconnect_machine(websocket, machine_id)


@router.websocket("/ws/user")
async def ws_user(websocket: WebSocket, token: str = Query(...)):
    user_id = _get_user_id(token)
    if not user_id:
        await websocket.close(code=4001)
        return

    await manager.connect_user(websocket, user_id)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect_user(websocket, user_id)
