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
MODELS_DIR = DATA_DIR / "models"          # обученные модели (LightGBM — текстом, коммитится)
AI_CACHE_DIR = DATA_DIR / "ai_cache"      # ответы LLM — для показа без интернета
FRONTEND_DIST = ROOT_DIR / "frontend" / "dist"


def load_dotenv(path: Path | None = None) -> None:
    """Переменные из `.env` в корне проекта. Уже заданные в окружении не перезаписываются."""
    path = path or ROOT_DIR / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].strip()
        if key and key not in os.environ:
            os.environ[key] = value


load_dotenv()

# Часовой пояс завода (Костанай, UTC+5) — во всех временных метках.
PLANT_TZ = timezone(timedelta(hours=5))
TZ_NAME = "UTC+05:00 (Костанай)"


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
