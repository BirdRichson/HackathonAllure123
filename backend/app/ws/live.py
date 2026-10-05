"""WebSocket `/ws/live`: при подключении — snapshot, затем tick каждые ~0,5 с, kpi каждые ~2 с."""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/ws/live")
async def live(ws: WebSocket) -> None:
    runtime = ws.app.state.runtime
    await ws.accept()
    await ws.send_json({"type": "snapshot", "payload": runtime.snapshot()})
    runtime.clients.add(ws)
    try:
        while True:
            await ws.receive_text()       # входящие сообщения не нужны, держим соединение
    except WebSocketDisconnect:
        pass
    finally:
        runtime.clients.discard(ws)
