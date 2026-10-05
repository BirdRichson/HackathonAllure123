"""Пути проекта и загрузка конфигов из `config/`."""

from __future__ import annotations

import os
from datetime import timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT_DIR = Path(os.environ.get("ALLUR_ROOT", Path(__file__).resolve().parents[2]))
CONFIG_DIR = ROOT_DIR / "config"
DATA_DIR = ROOT_DIR / "data"
TEST_DATA_DIR = DATA_DIR / "test"
FRONTEND_DIST = ROOT_DIR / "frontend" / "dist"

# Часовой пояс завода (Костанай, UTC+5) — во всех временных метках.
PLANT_TZ = timezone(timedelta(hours=5))


def _load_yaml(name: str) -> dict[str, Any]:
    with open(CONFIG_DIR / name, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@lru_cache
def plant_config() -> dict[str, Any]:
    return _load_yaml("plant.yaml")


@lru_cache
def targets_config() -> dict[str, Any]:
    return _load_yaml("targets.yaml")


@lru_cache
def reasons_config() -> dict[str, Any]:
    return _load_yaml("reasons.yaml")


def data_mode() -> str:
    """`demo` — симулятор, `plant` — загруженные данные завода."""
    return os.environ.get("ALLUR_DATA_MODE", "demo")
