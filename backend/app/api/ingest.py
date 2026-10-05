"""Импорт данных завода (docx, xlsx, csv) и результат последнего импорта."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request, UploadFile

from app.config import PLANT_TZ
from app.ingest.organizer import import_files

router = APIRouter(prefix="/api")

MAX_BYTES = 10 * 1024 * 1024


@router.post("/ingest")
async def ingest(request: Request, files: list[UploadFile]) -> dict[str, Any]:
    blobs = []
    for f in files:
        data = await f.read()
        if len(data) > MAX_BYTES:
            raise HTTPException(413, f"{f.filename}: файл больше 10 МБ")
        blobs.append((f.filename or "file", data))
    try:
        payload = import_files(blobs)
    except Exception as e:      # разбор чужих файлов: показываем понятную ошибку, а не 500
        raise HTTPException(422, f"Не удалось разобрать файлы: {e}") from e
    db = request.app.state.runtime.db
    imported_at = datetime.now(PLANT_TZ).isoformat(timespec="seconds")
    import_id = db.save_import(payload["files"], payload, imported_at)
    return {"id": import_id, "imported_at": imported_at, **payload}


@router.get("/ingest/latest")
def latest(request: Request) -> dict[str, Any]:
    res = request.app.state.runtime.db.latest_import()
    if res is None:
        raise HTTPException(404, "Данные завода ещё не загружались")
    return res
