"""Живой режим: симулятор идёт в реальном времени (×1…×300), изменения уходят в интерфейс по WebSocket.

World   — один «мир»: симулятор, прогретый на N суток назад, плюс инциденты и очередь изменений.
Runtime — управляет текущим миром: цикл времени, пауза, скорость, мгновенный сброс
          (запасной мир строится заранее в фоне), запись в БД и рассылка клиентам.
"""

from __future__ import annotations

import asyncio
import os
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.config import DATA_DIR, PLANT_TZ, ROOT_DIR, plant_config
from app.kpi.incidents import IncidentEngine
from app.sim.engine import DAY_MIN, PlantSim
from app.storage.db import Database


# ─────────────────────────────── настройки ────────────────────────────────────


def _live_start(cfg: dict) -> datetime:
    """Последний рабочий день (сегодня или раньше) в заданное время — «сейчас» на заводе при запуске демо."""
    env = os.environ.get("ALLUR_LIVE_START")
    if env:
        return datetime.fromisoformat(env).replace(tzinfo=None)
    today = datetime.now(PLANT_TZ).replace(tzinfo=None)
    workdays = set(plant_config()["schedule"]["working_weekdays"])
    d = today
    while d.isoweekday() not in workdays:
        d -= timedelta(days=1)
    h, m = cfg["start_time"].split(":")
    return d.replace(hour=int(h), minute=int(m), second=0, microsecond=0)


@dataclass
class Settings:
    seed: int
    start: datetime
    warmup_days: float
    speeds: list[int]
    default_speed: int
    tick_s: float
    telemetry_window_min: float
    db_path: Path
    run_loop: bool = True

    @classmethod
    def from_env(cls) -> "Settings":
        plant = plant_config()
        live = plant["live"]
        return cls(
            seed=int(os.environ.get("ALLUR_SEED", plant["simulation"]["seed"])),
            start=_live_start(live),
            warmup_days=float(os.environ.get("ALLUR_WARMUP_DAYS", live["warmup_days"])),
            speeds=[int(s) for s in live["speeds"]],
            default_speed=int(live["default_speed"]),
            tick_s=float(live["tick_s"]),
            telemetry_window_min=60 * float(live["telemetry_window_h"]),
            db_path=Path(os.environ.get("ALLUR_DB_PATH", DATA_DIR / "runtime" / "allur.db")),
            run_loop=os.environ.get("ALLUR_NO_LOOP") != "1",
        )


# ─────────────────────────────── мир ──────────────────────────────────────────


@dataclass
class Outbox:
    events: list[tuple] = field(default_factory=list)
    units: list[tuple] = field(default_factory=list)
    reports: dict[str, dict] = field(default_factory=dict)


class World:
    def __init__(self, settings: Settings, seed: int | None = None) -> None:
        self.seed = settings.seed if seed is None else seed
        self.live_start = settings.start
        sim_start = (settings.start - timedelta(days=settings.warmup_days)).replace(hour=0, minute=0)
        self.sim = PlantSim(plant_config(), seed=self.seed, start=sim_start,
                            telemetry_window_min=settings.telemetry_window_min)
        self.incidents = IncidentEngine(self.sim, self.iso)
        self.out = Outbox()
        self.reports: dict[str, dict] = {}
        self.user_touched: set[str] = set()      # отчёты, которые заполнил человек, — генератор их не перезаписывает
        self.sim.rec.listeners.append(self._on_record)
        self.sim.run_until((settings.start - sim_start).total_seconds() / 60)
        self.out = Outbox()          # события прогрева в живой поток не идут

    # время модели → ISO с часовым поясом завода
    def iso(self, t: float | None) -> str | None:
        if t is None:
            return None
        return (self.sim.cal.dt(t)).replace(tzinfo=PLANT_TZ).isoformat(timespec="seconds")

    def report_row(self, r: dict) -> dict:
        dur = None if r.get("t_end") is None else round(r["t_end"] - r["t_start"], 1)
        return {
            "id": r["id"], "equipment_id": r["equipment_id"], "area_id": r["area_id"],
            "ts_start": self.iso(r["t_start"]), "ts_end": self.iso(r.get("t_end")), "duration_min": dur,
            "source": r["source"], "status": r["status"], "reason": r["reason"],
            "description": r["description"], "actions_taken": r["actions_taken"],
            "reporter_role": r["reporter_role"], "machine_reason_text": r["machine_reason_text"],
            "true_reason": r["true_reason"], "true_subtype": r["true_subtype"],
        }

    def _on_record(self, kind: str, payload: Any) -> None:
        if kind == "state":
            self.out.events.append(payload)
        elif kind == "unit":
            self.out.units.append(payload)
        elif kind in ("report_open", "report_close"):
            row = self.report_row(payload)
            self.reports[row["id"]] = row
            self.out.reports[row["id"]] = row

    def drain(self) -> tuple[Outbox, list[dict]]:
        out, self.out = self.out, Outbox()
        return out, self.incidents.drain()


# ─────────────────────────────── рантайм ──────────────────────────────────────


class Runtime:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_env()
        self.db = Database(self.settings.db_path)
        self.speed = self.settings.default_speed
        self.paused = False
        self.clients: set[Any] = set()
        self._pool = ThreadPoolExecutor(max_workers=1)
        self._spare: Future | None = None
        self._task: asyncio.Task | None = None
        self._last_kpi = 0.0
        self.world = World(self.settings)
        self._install(self.world)
        self._ensure_default_import()

    # ── жизненный цикл ──

    def _install(self, world: World) -> None:
        world.drain()
        incidents = [dict(i) for i in world.incidents.items.values()]
        self.db.replace_live(list(world.reports.values()), incidents)
        self.world = world

    def _prepare_spare(self) -> None:
        self._spare = self._pool.submit(World, self.settings)

    def _ensure_default_import(self) -> None:
        """Данные организаторов загружаются при первом запуске — раздел «Данные завода» сразу заполнен."""
        if self.db.has_imports():
            return
        raw = sorted((ROOT_DIR / "data" / "raw").glob("*.docx"))
        if not raw:
            return
        from app.ingest.organizer import import_files
        files = [(p.name, p.read_bytes()) for p in raw]
        payload = import_files(files)
        self.db.save_import(payload["files"], payload, datetime.now(PLANT_TZ).isoformat(timespec="seconds"),
                            is_default=True)

    async def start(self) -> None:
        if self.settings.run_loop:
            self._task = asyncio.create_task(self._loop())
            self._prepare_spare()

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
        self._pool.shutdown(wait=False, cancel_futures=True)

    async def _loop(self) -> None:
        last = time.monotonic()
        while True:
            await asyncio.sleep(self.settings.tick_s)
            now = time.monotonic()
            dt, last = now - last, now
            self.advance(dt)
            await self.publish()

    def advance(self, real_seconds: float) -> None:
        """Сдвинуть модель на real_seconds × скорость (модельные минуты)."""
        if not self.paused:
            sim = self.world.sim
            sim.run_until(sim.now + self.speed * real_seconds / 60.0)

    # ── управление ──

    def control(self, speed: int | None = None, paused: bool | None = None) -> dict:
        if speed is not None:
            if speed not in self.settings.speeds:
                raise ValueError(f"скорость должна быть одной из {self.settings.speeds}")
            self.speed = speed
        if paused is not None:
            self.paused = paused
        return self.status()

    async def reset(self, seed: int | None = None) -> dict:
        """Сброс демо в исходное состояние. Запасной мир уже прогрет — сброс почти мгновенный."""
        if seed is None and self._spare is not None:
            world = await asyncio.wrap_future(self._spare)
        else:
            world = await asyncio.to_thread(World, self.settings, seed)
        self._install(world)
        self.paused = False
        self.speed = self.settings.default_speed
        if self.settings.run_loop:
            self._prepare_spare()
        await self.broadcast({"type": "snapshot", "payload": self.snapshot()})
        return self.status()

    def status(self) -> dict:
        sim = self.world.sim
        return {"sim_time": self.world.iso(sim.now), "speed": self.speed, "paused": self.paused,
                "speeds": self.settings.speeds, "seed": self.world.seed}

    # ── рассылка ──

    async def broadcast(self, msg: dict) -> None:
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_json(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    async def publish(self) -> None:
        from app import views

        out, incidents = self.world.drain()
        rows = []
        for rid, row in out.reports.items():
            if rid in self.world.user_touched and "true_reason" in row:
                rows.append({"id": rid, "ts_end": row["ts_end"], "duration_min": row["duration_min"]})
            else:
                rows.append({k: v for k, v in row.items()})
        self.db.upsert_reports(rows)
        out.reports = {rid: {k: v for k, v in r.items() if k not in ("true_reason", "true_subtype")}
                       for rid, r in out.reports.items()}
        self.db.upsert_incidents(incidents)
        if not self.clients:
            return
        payload = views.tick_payload(self, out, incidents)
        await self.broadcast({"type": "tick", "payload": payload})
        now = time.monotonic()
        if now - self._last_kpi >= 2.0:
            self._last_kpi = now
            await self.broadcast({"type": "kpi", "payload": views.kpi_now(self)})

    def snapshot(self) -> dict:
        from app import views
        return views.snapshot(self)

    # ── отчёты рабочих ──

    def submit_report(self, data: dict) -> dict:
        """Отчёт с формы рабочего. Если по оборудованию есть черновик от станка — дополняет его."""
        world = self.world
        values = {k: data.get(k) or "" for k in ("reason", "description", "actions_taken", "reporter_role")}
        values.update(status="completed", source=data.get("source") or "operator_form")
        target = None
        if data.get("report_id"):                  # рабочий выбрал конкретную запись в журнале
            target = self.db.get_report(data["report_id"])
        elif data.get("complete_draft", True):     # иначе — свежий черновик станка (идёт сейчас или до 2 ч назад)
            drafts = self.db.list_reports(equipment=data["equipment_id"], status="draft", limit=1)
            if drafts and drafts[0]["source"] == "machine":
                end = drafts[0]["ts_end"] or world.iso(world.sim.now)
                age_min = (datetime.fromisoformat(world.iso(world.sim.now)) - datetime.fromisoformat(end)).total_seconds() / 60
                if age_min <= 120:
                    target = drafts[0]
        if target is not None and target["equipment_id"] == data["equipment_id"]:
            rid = target["id"]
            self.db.update_report(rid, values)
            world.user_touched.add(rid)
        else:
            sim = world.sim
            n = len([k for k in world.reports if k.startswith("R-U")]) + 1
            rid = f"R-U{n:04d}"
            dur = float(data.get("duration_min") or 0)
            eq = sim.equipment[data["equipment_id"]]
            row = {"id": rid, "equipment_id": eq.id, "area_id": eq.area_id,
                   "ts_start": world.iso(sim.now - dur), "ts_end": world.iso(sim.now), "duration_min": dur,
                   "machine_reason_text": "", "true_reason": "", "true_subtype": "", **values}
            world.reports[rid] = row
            world.user_touched.add(rid)
            self.db.upsert_reports([row])
        report = self.db.get_report(rid)
        world.out.reports[rid] = {**report}
        return report

    def complete_report(self, rid: str, data: dict) -> dict | None:
        if not self.db.get_report(rid):
            return None
        values = {k: v for k, v in data.items() if k in ("reason", "description", "actions_taken", "reporter_role")
                  and v is not None}
        if values.get("description") or values.get("reason"):
            values["status"] = "completed"
            values.setdefault("source", "operator_form")
        self.db.update_report(rid, values)
        self.world.user_touched.add(rid)
        report = self.db.get_report(rid)
        self.world.out.reports[rid] = {**report}
        return report


def minutes_of_day(t: float) -> float:
    return t - (t // DAY_MIN) * DAY_MIN
