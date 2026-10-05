"""Точка входа FastAPI: `uvicorn app.main:app` из папки backend."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.ai import router as ai_router
from app.api.ingest import router as ingest_router
from app.api.live import router as live_router
from app.api.reports import router as reports_router
from app.api.routes import router as api_router
from app.config import FRONTEND_DIST
from app.runtime import Runtime
from app.ws.live import router as ws_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Прогрев симулятора (~3 с): завод «проживает» последние 30 суток, чтобы были история и статистика.
    runtime = Runtime()
    app.state.runtime = runtime
    await runtime.start()
    yield
    await runtime.stop()


def create_app() -> FastAPI:
    app = FastAPI(title="Цифровой двойник АЛЛЮР", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for r in (api_router, live_router, reports_router, ai_router, ingest_router, ws_router):
        app.include_router(r)

    # Режим демо на одном ноутбуке: если интерфейс собран, бэкенд отдаёт его сам.
    if FRONTEND_DIST.is_dir():
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
    return app


app = create_app()
