"""Точка входа FastAPI: `uvicorn app.main:app` из папки backend."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.routes import router as api_router
from app.config import FRONTEND_DIST


def create_app() -> FastAPI:
    app = FastAPI(title="Цифровой двойник АЛЛЮР", version=__version__)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)

    # Режим демо на одном ноутбуке: если фронтенд собран, бэкенд отдаёт его сам.
    if FRONTEND_DIST.is_dir():
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
    return app


app = create_app()
