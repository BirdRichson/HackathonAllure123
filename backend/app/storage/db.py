"""Хранилище (SQLite через SQLAlchemy): отчёты о простоях, инциденты, импорт данных завода.

Живое состояние станков и телеметрия держатся в памяти симулятора, история — в parquet.
В промышленной версии это место занимает PostgreSQL/TimescaleDB, а схема таблиц остаётся той же.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import (Boolean, Column, Float, Integer, MetaData, String, Table, Text, create_engine, delete,
                        insert, select, update)

metadata = MetaData()

reports = Table(
    "reports", metadata,
    Column("id", String, primary_key=True),
    Column("equipment_id", String, index=True),
    Column("area_id", String, index=True),
    Column("ts_start", String, index=True),
    Column("ts_end", String),
    Column("duration_min", Float),
    Column("source", String),            # machine | operator_form | telegram | import
    Column("status", String),            # draft | completed
    Column("reason", String),            # причина, выбранная рабочим
    Column("description", Text),
    Column("actions_taken", Text),
    Column("reporter_role", String),
    Column("machine_reason_text", String),
    # Истина симулятора — только для оценки ИИ, в интерфейс не отдаётся.
    Column("true_reason", String),
    Column("true_subtype", String),
)

incidents = Table(
    "incidents", metadata,
    Column("id", String, primary_key=True),
    Column("key", String, unique=True),
    Column("ts_start", String, index=True),
    Column("ts_end", String),
    Column("status", String),            # open | closed
    Column("severity", String),          # info | warning | critical
    Column("type", String),              # downtime | quality | threshold | oee | prediction
    Column("area_id", String, index=True),
    Column("equipment_id", String),
    Column("title", Text),
    Column("details", Text),
)

imports = Table(
    "imports", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("imported_at", String),
    Column("files", Text),
    Column("payload", Text),             # результат разбора и анализа (JSON)
    Column("is_default", Boolean, default=False),
)

PUBLIC_REPORT_FIELDS = ["id", "equipment_id", "area_id", "ts_start", "ts_end", "duration_min", "source", "status",
                        "reason", "description", "actions_taken", "reporter_role", "machine_reason_text"]


class Database:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
        metadata.create_all(self.engine)

    # ── отчёты и инциденты ──

    def replace_live(self, report_rows: list[dict], incident_rows: list[dict]) -> None:
        """Полная замена живых данных — при старте и сбросе демо."""
        with self.engine.begin() as c:
            c.execute(delete(reports))
            c.execute(delete(incidents))
            if report_rows:
                c.execute(insert(reports), report_rows)
            if incident_rows:
                c.execute(insert(incidents), incident_rows)

    def upsert_reports(self, rows: list[dict]) -> None:
        if not rows:
            return
        with self.engine.begin() as c:
            for r in rows:
                if c.execute(select(reports.c.id).where(reports.c.id == r["id"])).first():
                    c.execute(update(reports).where(reports.c.id == r["id"]).values(**r))
                else:
                    c.execute(insert(reports).values(**r))

    def upsert_incidents(self, rows: list[dict]) -> None:
        if not rows:
            return
        with self.engine.begin() as c:
            for r in rows:
                if c.execute(select(incidents.c.id).where(incidents.c.id == r["id"])).first():
                    c.execute(update(incidents).where(incidents.c.id == r["id"]).values(**r))
                else:
                    c.execute(insert(incidents).values(**r))

    def list_reports(self, area: str | None = None, equipment: str | None = None, status: str | None = None,
                     limit: int = 100, include_truth: bool = False) -> list[dict]:
        cols = [reports.c[f] for f in PUBLIC_REPORT_FIELDS]
        if include_truth:
            cols += [reports.c.true_reason, reports.c.true_subtype]
        q = select(*cols).order_by(reports.c.ts_start.desc()).limit(limit)
        if area:
            q = q.where(reports.c.area_id == area)
        if equipment:
            q = q.where(reports.c.equipment_id == equipment)
        if status:
            q = q.where(reports.c.status == status)
        with self.engine.connect() as c:
            return [dict(r._mapping) for r in c.execute(q)]

    def get_report(self, report_id: str) -> dict | None:
        with self.engine.connect() as c:
            row = c.execute(select(*[reports.c[f] for f in PUBLIC_REPORT_FIELDS])
                            .where(reports.c.id == report_id)).first()
            return dict(row._mapping) if row else None

    def update_report(self, report_id: str, values: dict) -> None:
        with self.engine.begin() as c:
            c.execute(update(reports).where(reports.c.id == report_id).values(**values))

    def list_incidents(self, status: str | None = None, area: str | None = None, limit: int = 100) -> list[dict]:
        q = select(incidents).order_by(incidents.c.ts_start.desc()).limit(limit)
        if status:
            q = q.where(incidents.c.status == status)
        if area:
            q = q.where(incidents.c.area_id == area)
        with self.engine.connect() as c:
            return [{k: v for k, v in dict(r._mapping).items() if k != "key"} for r in c.execute(q)]

    # ── импорт данных завода ──

    def save_import(self, files: list[str], payload: dict, imported_at: str, is_default: bool = False) -> int:
        with self.engine.begin() as c:
            res = c.execute(insert(imports).values(imported_at=imported_at, files=json.dumps(files, ensure_ascii=False),
                                                   payload=json.dumps(payload, ensure_ascii=False, default=str),
                                                   is_default=is_default))
            return int(res.inserted_primary_key[0])

    def latest_import(self) -> dict[str, Any] | None:
        with self.engine.connect() as c:
            row = c.execute(select(imports).order_by(imports.c.id.desc()).limit(1)).first()
        if not row:
            return None
        m = dict(row._mapping)
        return {"id": m["id"], "imported_at": m["imported_at"], "files": json.loads(m["files"]),
                "is_default": m["is_default"], **json.loads(m["payload"])}

    def has_imports(self) -> bool:
        with self.engine.connect() as c:
            return c.execute(select(imports.c.id).limit(1)).first() is not None
