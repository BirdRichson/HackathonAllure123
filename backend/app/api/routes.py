"""Базовые эндпоинты: здоровье сервиса, целевые показатели, схема завода."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter

from app import __version__
from app.config import PLANT_TZ, data_mode, plant_config, targets_config

router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "version": __version__,
        "data_mode": data_mode(),
        "time": datetime.now(PLANT_TZ).isoformat(timespec="seconds"),
    }


@router.get("/targets")
def targets() -> dict[str, Any]:
    return targets_config()


@router.get("/plant")
def plant() -> dict[str, Any]:
    return plant_config()
