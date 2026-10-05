"""Дискретно-событийный симулятор завода (SimPy).

Как устроено (подробнее — docs/EXPLAIN.md):
- Время модели — минуты от полуночи даты `start`. Работают 2 смены (08–16, 16–24) в будни.
- Кузов идёт: склад CKD → сварка → окраска → сборка → контроль → склад готовой продукции.
  Между участками — буферы ограниченной ёмкости; пустой буфер = «нет входа», полный = «выход занят».
- Участок обрабатывает по одному кузову за цикл и стоит, если стоит любое его оборудование
  (линия последовательная, решение D5).
- У оборудования есть наработка (моточасы). Отказ наступает, когда наработка достигает заранее
  выбранного срока (распределение Вейбулла). Для износовых отказов (цепь, горелка) телеметрия
  за 1–3 часа до отказа плавно растёт — это «предвестник», на котором учится ИИ.
- Фильтр камеры окраски засоряется: растёт перепад давления, вместе с ним брак (сорность),
  на пределе — вынужденная замена ≈40 мин.
- Плановое ТО — по моточасам, в начале смены (как сейчас на заводе) или ночью (режим `night`).
- На каждую остановку станка рабочий пишет отчёт (см. report_texts.py).
"""

from __future__ import annotations

import math
import zlib
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable

import numpy as np
import simpy

from app.sim.report_texts import make_report_text

DAY_MIN = 1440.0


def rng_for(seed: int, name: str) -> np.random.Generator:
    """Отдельный воспроизводимый генератор для каждого компонента."""
    return np.random.default_rng([seed, zlib.crc32(name.encode("utf-8"))])


def _hhmm(s: str) -> float:
    h, m = s.split(":")
    total = int(h) * 60 + int(m)
    return float(total if total else DAY_MIN)


# ─────────────────────────────── календарь смен ───────────────────────────────


class Calendar:
    def __init__(self, start: datetime, shifts: list[dict], weekdays: list[int]) -> None:
        self.start = start.replace(hour=0, minute=0, second=0, microsecond=0)
        self.shifts = [(int(s["id"]), _hhmm(s["start"]) % DAY_MIN, _hhmm(s["end"])) for s in shifts]
        self.weekdays = set(weekdays)

    def dt(self, t: float) -> datetime:
        return self.start + timedelta(minutes=t)

    def _is_workday(self, day: int) -> bool:
        return (self.start + timedelta(days=day)).isoweekday() in self.weekdays

    def shift_at(self, t: float) -> tuple[int, int] | None:
        """(номер дня от старта, номер смены) или None вне смены."""
        day = int(t // DAY_MIN)
        if not self._is_workday(day):
            return None
        m = t - day * DAY_MIN
        for sid, s0, s1 in self.shifts:
            if s0 <= m < s1:
                return day, sid
        return None

    def in_shift(self, t: float) -> bool:
        return self.shift_at(t) is not None

    def shift_end(self, t: float) -> float:
        """Конец текущей смены (t должен быть внутри смены)."""
        day = int(t // DAY_MIN)
        m = t - day * DAY_MIN
        for _, s0, s1 in self.shifts:
            if s0 <= m < s1:
                return day * DAY_MIN + s1
        return t

    def next_shift_start(self, t: float) -> float:
        day = int(t // DAY_MIN)
        for d in range(day, day + 10):
            if not self._is_workday(d):
                continue
            for _, s0, _ in self.shifts:
                start = d * DAY_MIN + s0
                if start > t + 1e-9:
                    return start
        raise RuntimeError("не найдено следующей смены")

    def shift_windows(self, t0: float, t1: float) -> list[tuple[int, int, float, float]]:
        """Все смены в интервале [t0, t1): (день, смена, начало, конец)."""
        out = []
        for day in range(int(t0 // DAY_MIN), int(math.ceil(t1 / DAY_MIN)) + 1):
            if not self._is_workday(day):
                continue
            for sid, s0, s1 in self.shifts:
                a, b = day * DAY_MIN + s0, day * DAY_MIN + s1
                if a >= t0 - 1e-9 and b <= t1 + 1e-9:
                    out.append((day, sid, a, b))
        return out


# ─────────────────────────────── запись результатов ───────────────────────────


class Recorder:
    """Копит события модели. Слушатели (`listeners`) получают их сразу — для живого потока."""

    def __init__(self, telemetry: bool = True, telemetry_window_min: float | None = None) -> None:
        self.record_telemetry = telemetry
        self.telemetry_window = telemetry_window_min   # None — хранить всё (история), иначе скользящее окно (живой режим)
        self.events: list[tuple] = []      # (t, scope, id, area_id, state, reason, reason_text, planned)
        self.telemetry: deque = deque()    # (t, equipment_id, temperature, vibration, current, cycle_time, filter_dp)
        self.last_telemetry: dict[str, tuple] = {}
        self.units: list[tuple] = []       # (t, unit_id, model, area_id, defect_code)
        self.reports: list[dict] = []
        self.listeners: list[Callable[[str, Any], None]] = []

    def _emit(self, kind: str, payload: Any) -> None:
        for fn in self.listeners:
            fn(kind, payload)

    def state(self, row: tuple) -> None:
        self.events.append(row)
        self._emit("state", row)

    def tele(self, row: tuple) -> None:
        self.last_telemetry[row[1]] = row
        if self.record_telemetry:
            self.telemetry.append(row)
            if self.telemetry_window is not None:
                cutoff = row[0] - self.telemetry_window
                while self.telemetry and self.telemetry[0][0] < cutoff:
                    self.telemetry.popleft()
        self._emit("telemetry", row)

    def unit(self, row: tuple) -> None:
        self.units.append(row)
        self._emit("unit", row)

    def report_open(self, report: dict) -> None:
        self._emit("report_open", report)

    def report_close(self, report: dict) -> None:
        self.reports.append(report)
        self._emit("report_close", report)


# ─────────────────────────────── оборудование ─────────────────────────────────


def weibull(rng: np.random.Generator, shape: float, scale: float, age: float = 0.0) -> float:
    """Наработка до отказа при условии, что до `age` отказа не было."""
    u = rng.random()
    return scale * ((age / scale) ** shape - math.log(1.0 - u)) ** (1.0 / shape)


def lognormal_min(rng: np.random.Generator, spec: dict) -> float:
    return float(spec["median"] * math.exp(rng.normal(0.0, spec["sigma"])))


@dataclass
class ModeState:
    cfg: dict
    ttf_h: float          # наработка, при которой случится отказ
    age_h: float          # текущая наработка с последнего обновления
    lead_h: float = 0.0   # длина окна предвестника

    @property
    def wear(self) -> bool:
        return float(self.cfg["weibull"]["shape"]) > 1.0

    def precursor_progress(self) -> float:
        if not self.cfg.get("precursor") or self.lead_h <= 0:
            return 0.0
        return min(1.0, max(0.0, (self.age_h - (self.ttf_h - self.lead_h)) / self.lead_h))


@dataclass
class Equipment:
    id: str
    name: str
    area_id: str
    type: str
    tcfg: dict
    rng: np.random.Generator
    status: str = "ok"                 # ok | down | maintenance
    since_to_h: float = 0.0
    to_due: bool = False
    modes: list[ModeState] = field(default_factory=list)
    filter_age_h: float = 0.0
    filter_life_h: float = 0.0
    last_to_t: float | None = None

    @property
    def interval_h(self) -> float:
        return float(self.tcfg["maintenance"]["interval_h"])

    # Перепад давления на фильтре камеры: растёт с наработкой, ускоряясь к концу ресурса.
    def filter_dp(self) -> float | None:
        f = self.tcfg.get("filter")
        if not f:
            return None
        frac = min(1.2, self.filter_age_h / max(self.filter_life_h, 1e-6))
        return f["dp_new_pa"] + (f["dp_limit_pa"] - f["dp_new_pa"]) * frac**1.6

    def sample_lead(self, mode: ModeState) -> None:
        pre = mode.cfg.get("precursor")
        if pre:
            lo, hi = pre["lead_min"]
            mode.lead_h = float(self.rng.uniform(lo, hi)) / 60.0

    def renew_mode(self, mode: ModeState) -> None:
        w = mode.cfg["weibull"]
        mode.age_h = 0.0
        mode.ttf_h = weibull(self.rng, w["shape"], w["scale_h"])
        self.sample_lead(mode)

    def renew_filter(self) -> None:
        mu, sd = self.tcfg["filter"]["life_h"]
        self.filter_age_h = 0.0
        self.filter_life_h = float(np.clip(self.rng.normal(mu, sd), 0.5 * mu, 1.6 * mu))

    def telemetry(self, cycle_s: float) -> tuple:
        t = self.tcfg["telemetry"]
        rng = self.rng
        temp_mu, temp_sd = t["temperature"]
        temp = rng.normal(temp_mu, temp_sd)
        vib = rng.normal(*t["vibration"])
        cur = rng.normal(*t["current"])
        for m in self.modes:
            pre = m.cfg.get("precursor") or {}
            p = m.precursor_progress()
            if m.wear:   # медленный износ: вибрация чуть растёт с наработкой
                vib *= 1.0 + 0.12 * min(m.age_h / m.cfg["weibull"]["scale_h"], 1.5)
            if p > 0:
                cur *= 1.0 + pre.get("current", 0.0) * p**2
                vib *= 1.0 + pre.get("vibration", 0.0) * p**2
                if "temperature_std_x" in pre:
                    temp = temp_mu + (temp - temp_mu) * (1.0 + (pre["temperature_std_x"] - 1.0) * p)
        dp = self.filter_dp()
        if dp is not None:
            f = self.tcfg["filter"]
            cur *= 1.0 + 0.15 * (dp - f["dp_new_pa"]) / (f["dp_limit_pa"] - f["dp_new_pa"])
            dp = dp + rng.normal(0, 5.0)
        return (round(temp, 2), round(max(vib, 0.0), 3), round(max(cur, 0.0), 2),
                round(cycle_s, 1), None if dp is None else round(dp, 1))


# ─────────────────────────────── участки ──────────────────────────────────────


@dataclass
class Unit:
    id: str
    model: str


@dataclass
class Area:
    id: str
    name: str
    proc: dict | None
    equipment: list[Equipment]
    in_buf: deque | None = None
    in_cap: int | None = None
    out_buf: deque | None = None
    out_cap: int | None = None
    state: str = "offline"
    blockers: dict[str, tuple] = field(default_factory=dict)  # кто держит участок: (state, reason, text, planned)
    up_event: simpy.Event | None = None
    process: simpy.Process | None = None
    busy: bool = False
    last_cycle_s: float = 0.0
    last_key: tuple | None = None     # последнее записанное состояние — чтобы не дублировать события


STATE_PRIORITY = {"down": 0, "maintenance": 1, "setup": 2}


# ─────────────────────────────── модель завода ────────────────────────────────


class PlantSim:
    def __init__(
        self,
        plant: dict,
        seed: int | None = None,
        start: datetime | None = None,
        telemetry: bool = True,
        maintenance_window: str | None = None,
        telemetry_window_min: float | None = None,
    ) -> None:
        sim = plant["simulation"]
        self.plant = plant
        self.seed = int(sim["seed"] if seed is None else seed)
        start = start or datetime.fromisoformat(sim["history_end"]) - timedelta(days=int(sim["history_days"]))
        self.cal = Calendar(start, plant["schedule"]["shifts"], plant["schedule"]["working_weekdays"])
        self.env = simpy.Environment()
        self.rec = Recorder(telemetry=telemetry, telemetry_window_min=telemetry_window_min)
        # Оборудование, по которому отчёт заполнит человек (сценарий демо), а не генератор текста.
        self.manual_reports: set[str] = set()
        self.window = maintenance_window or sim.get("maintenance_window", "in_shift")
        self.step = float(sim.get("telemetry_step_min", 1))
        self._report_seq = 0
        self._unit_seq = 0

        self._build(plant)
        for area in self.areas.values():
            if area.proc is not None:
                area.process = self.env.process(self._area_proc(area))
                self.env.process(self._micro_stops(area))
        for eq in self.equipment.values():
            self.env.process(self._equipment_proc(eq))
        self.env.process(self._supply_proc())

    # ── построение ──

    def _build(self, plant: dict) -> None:
        types = plant["equipment_types"]
        self.equipment: dict[str, Equipment] = {}
        for e in plant["equipment"]:
            tcfg = types[e["type"]]
            eq = Equipment(e["id"], e["name"], e["area"], e["type"], tcfg, rng_for(self.seed, "eq:" + e["id"]))
            # Случайная «фаза» — чтобы ТО и отказы не шли синхронно с первого дня.
            eq.since_to_h = float(eq.rng.uniform(0, eq.interval_h))
            for m in tcfg.get("failure_modes", []):
                w = m["weibull"]
                age = eq.since_to_h if float(w["shape"]) > 1.0 else 0.0
                ms = ModeState(m, weibull(eq.rng, w["shape"], w["scale_h"], age), age)
                eq.sample_lead(ms)
                eq.modes.append(ms)
            if tcfg.get("filter"):
                eq.renew_filter()
                eq.filter_age_h = float(eq.rng.uniform(0, 0.8 * eq.filter_life_h))
            self.equipment[eq.id] = eq

        procs = plant["process"]
        self.areas: dict[str, Area] = {}
        for a in plant["areas"]:
            eqs = [eq for eq in self.equipment.values() if eq.area_id == a["id"]]
            self.areas[a["id"]] = Area(a["id"], a["name"], procs.get(a["id"]), eqs)
        self.area_rng = {aid: rng_for(self.seed, "area:" + aid) for aid in self.areas}

        # Буферы между соседними участками производственного потока.
        caps = {(b["from"], b["to"]): b.get("capacity") for b in plant["buffers"]}
        flow = plant["flow"]
        for up, down in zip(flow, flow[1:]):
            if up == "WH":
                continue   # склад CKD — отдельный счётчик комплектов
            buf: deque = deque()
            cap = caps.get((up, down))
            self.areas[up].out_buf, self.areas[up].out_cap = buf, cap
            self.areas[down].in_buf, self.areas[down].in_cap = buf, cap
        self.first_area = flow[1]
        self.wh_stock = int(plant["supply"]["initial_stock"])

        # Последовательность моделей: партии по 40–80 кузовов в пропорции месячного плана.
        self.models = [m["name"] for m in plant["models"]]
        w = np.array([m["plan_month_units"] for m in plant["models"]], dtype=float)
        self.model_w = w / w.sum()
        self.model_rng = rng_for(self.seed, "models")
        self._batch_left = 0
        self._batch_model = self.models[0]
        self._last_weld_model: str | None = None

    # ── вспомогательное ──

    @property
    def now(self) -> float:
        return self.env.now

    def _next_model(self) -> str:
        if self._batch_left <= 0:
            lo, hi = self.plant["changeover"]["batch_size"]
            self._batch_left = int(self.model_rng.integers(lo, hi + 1))
            self._batch_model = str(self.model_rng.choice(self.models, p=self.model_w))
        self._batch_left -= 1
        return self._batch_model

    def _set_area_state(self, area: Area, state: str, reason: str = "", text: str = "", planned: bool = False) -> None:
        key = (state, reason, text)
        if area.last_key == key:
            return
        area.last_key = key
        area.state = state
        self.rec.state((self.now, "area", area.id, area.id, state, reason, text, planned))

    def _refresh_blocked(self, area: Area) -> None:
        """Показать причину остановки участка и прервать текущий цикл."""
        if area.blockers:
            st, reason, text, planned = sorted(area.blockers.values(), key=lambda b: STATE_PRIORITY.get(b[0], 9))[0]
            if self.cal.in_shift(self.now):
                self._set_area_state(area, st, reason, text, planned)
            if area.busy and area.process is not None:
                area.busy = False   # повторное прерывание того же цикла недопустимо
                area.process.interrupt()

    def _block(self, area: Area, key: str, info: tuple) -> None:
        area.blockers[key] = info
        self._refresh_blocked(area)

    def _unblock(self, area: Area, key: str) -> None:
        area.blockers.pop(key, None)
        if not area.blockers and area.up_event is not None and not area.up_event.triggered:
            area.up_event.succeed()

    def _wait_up(self, area: Area):
        area.up_event = self.env.event()
        return area.up_event

    # ── процессы ──

    def _supply_proc(self):
        s = self.plant["supply"]
        at = _hhmm(s["delivery_time"]) % DAY_MIN
        while True:
            day = int(self.now // DAY_MIN)
            t = day * DAY_MIN + at
            if t <= self.now:
                t += DAY_MIN
            yield self.env.timeout(t - self.now)
            if self.cal.dt(self.now).isoweekday() in s["delivery_weekdays"]:
                self.wh_stock += int(s["delivery_units"])

    def _area_proc(self, area: Area):
        rng = self.area_rng[area.id]
        proc = area.proc or {}
        while True:
            if not self.cal.in_shift(self.now):
                self._set_area_state(area, "offline")
                yield self.env.timeout(self.cal.next_shift_start(self.now) - self.now)
                continue
            if area.blockers:
                self._refresh_blocked(area)
                yield self._wait_up(area)
                continue

            # Вход: комплекты со склада или кузов из буфера.
            if area.id == self.first_area:
                if self.wh_stock <= 0:
                    self._set_area_state(area, "starved", "no_material", "Нет комплектующих")
                    yield self.env.timeout(1.0)
                    continue
            elif not area.in_buf:
                self._set_area_state(area, "starved", "starved", "Нет входа")
                yield self.env.timeout(0.25)
                continue

            if area.id == self.first_area:
                model = self._next_model()
                if self._last_weld_model is not None and model != self._last_weld_model:
                    lo, hi = self.plant["changeover"]["minutes"]
                    self._set_area_state(area, "setup", "changeover", f"Переналадка на {model}", True)
                    yield self.env.timeout(float(rng.uniform(lo, hi)))
                self._last_weld_model = model
                self.wh_stock -= 1
                self._unit_seq += 1
                unit = Unit(f"U-{self._unit_seq:06d}", model)
            else:
                unit = area.in_buf.popleft()

            # Цикл обработки. Остановка оборудования прерывает его, а конец смены ставит на паузу —
            # остаток цикла дорабатывается после ремонта или в следующую смену.
            remaining = max(0.5, rng.normal(proc["cycle_min"], proc["cycle_min"] * proc["cycle_cv"]))
            area.last_cycle_s = remaining * 60
            while remaining > 1e-6:
                if area.blockers:
                    self._refresh_blocked(area)
                    yield self._wait_up(area)
                    continue
                if not self.cal.in_shift(self.now):
                    self._set_area_state(area, "offline")
                    yield self.env.timeout(self.cal.next_shift_start(self.now) - self.now)
                    continue
                self._set_area_state(area, "running")
                chunk = min(remaining, self.cal.shift_end(self.now) - self.now)
                t0 = self.now
                area.busy = True
                try:
                    yield self.env.timeout(chunk)
                    remaining -= chunk
                except simpy.Interrupt:
                    remaining -= self.now - t0
                finally:
                    area.busy = False

            self.rec.unit((self.now, unit.id, unit.model, area.id, self._defect(area, rng)))

            # Выход: если следующий буфер полон — «выход занят».
            if area.out_buf is not None:
                while area.out_cap is not None and len(area.out_buf) >= area.out_cap:
                    if area.blockers:
                        self._refresh_blocked(area)
                        yield self._wait_up(area)
                        continue
                    if not self.cal.in_shift(self.now):
                        self._set_area_state(area, "offline")
                        yield self.env.timeout(self.cal.next_shift_start(self.now) - self.now)
                        continue
                    self._set_area_state(area, "blocked", "blocked", "Выход занят")
                    yield self.env.timeout(0.25)
                area.out_buf.append(unit)

    def _defect(self, area: Area, rng: np.random.Generator) -> str:
        proc = area.proc or {}
        base = float(proc.get("defect_rate", 0.0))
        extra = []
        for eq in area.equipment:   # сорность от засорённых фильтров камер окраски
            f = eq.tcfg.get("filter")
            dp = eq.filter_dp()
            if f and dp is not None:
                x = (dp - f["dp_defect_from_pa"]) / (f["dp_limit_pa"] - f["dp_defect_from_pa"])
                extra.append(f["defect_rate_at_limit"] * float(np.clip(x, 0.0, 1.0)))
        p_ok = (1.0 - base) * float(np.prod([1.0 - e for e in extra])) if extra else 1.0 - base
        if rng.random() >= 1.0 - p_ok:
            return ""
        codes = proc.get("defect_codes") or {}
        if extra and rng.random() < sum(extra) / (base + sum(extra)):
            return "PAINT_DIRT"
        if not codes:
            return "DEFECT"
        names = list(codes)
        w = np.array([codes[n] for n in names], dtype=float)
        return str(rng.choice(names, p=w / w.sum()))

    def _micro_stops(self, area: Area):
        cfg = self.plant["micro_stops"]
        rng = rng_for(self.seed, "micro:" + area.id)
        while True:
            yield self.env.timeout(float(rng.exponential(cfg["mean_interval_min"])))
            if area.state != "running" or not self.cal.in_shift(self.now):
                continue
            lo, hi = cfg["minutes"]
            dur = float(rng.uniform(lo, hi))
            t0 = self.now
            self._block(area, "micro", ("down", "other", "Микроостановка", False))
            yield self.env.timeout(dur)
            self._unblock(area, "micro")
            if rng.random() < cfg["report_probability"]:
                eq = area.equipment[int(rng.integers(len(area.equipment)))] if area.equipment else None
                if eq is not None:
                    self._close_report(self._open_report(eq, "other", "микроостановка", t0, "Микроостановка"), dur)

    def _equipment_proc(self, eq: Equipment):
        area = self.areas[eq.area_id]
        dt_h = self.step / 60.0
        while True:
            if not self.cal.in_shift(self.now):
                if eq.to_due and self.window == "night":
                    yield from self._maintenance(eq, area, in_shift=False)
                yield self.env.timeout(self.cal.next_shift_start(self.now) - self.now)
                # Плановое ТО в начале смены — так работает завод сейчас.
                if eq.to_due and self.window == "in_shift":
                    yield from self._maintenance(eq, area, in_shift=True)
                continue

            if area.state == "running":
                eq.since_to_h += dt_h
                for m in eq.modes:
                    m.age_h += dt_h
                if eq.tcfg.get("filter"):
                    eq.filter_age_h += dt_h
            self.rec.tele((self.now, eq.id, *eq.telemetry(area.last_cycle_s)))

            failed = next((m for m in eq.modes if m.age_h >= m.ttf_h), None)
            if failed is not None:
                yield from self._failure(eq, area, failed)
                continue
            f = eq.tcfg.get("filter")
            if f and eq.filter_age_h >= eq.filter_life_h:
                yield from self._filter_change(eq, area)
                continue
            if eq.since_to_h >= eq.interval_h:
                eq.to_due = True
            yield self.env.timeout(self.step)

    def _equipment_state(self, eq: Equipment, status: str, reason: str = "", text: str = "", planned: bool = False):
        eq.status = status
        self.rec.state((self.now, "equipment", eq.id, eq.area_id, "running" if status == "ok" else status,
                        reason, text, planned))

    def _stop(self, eq: Equipment, area: Area, status: str, reason: str, text: str, planned: bool) -> None:
        self._equipment_state(eq, status, reason, text, planned)
        self._block(area, eq.id, (status, reason, text, planned))

    def _resume(self, eq: Equipment, area: Area) -> None:
        self._equipment_state(eq, "ok")
        self._unblock(area, eq.id)

    def _failure(self, eq: Equipment, area: Area, mode: ModeState):
        cfg = mode.cfg
        t0 = self.now
        self._stop(eq, area, "down", cfg["reason"], cfg["reason_text"], False)
        rep = self._open_report(eq, cfg["reason"], cfg["subtype"], t0, cfg["reason_text"])
        dur = lognormal_min(eq.rng, cfg["repair_min"])
        yield self.env.timeout(dur)
        eq.renew_mode(mode)
        self._resume(eq, area)
        self._close_report(rep, dur)

    def _filter_change(self, eq: Equipment, area: Area):
        f = eq.tcfg["filter"]
        t0 = self.now
        self._stop(eq, area, "down", f["reason"], f["reason_text"], False)
        rep = self._open_report(eq, f["reason"], f["subtype"], t0, f["reason_text"])
        dur = lognormal_min(eq.rng, f["replace_min"])
        yield self.env.timeout(dur)
        eq.renew_filter()
        self._resume(eq, area)
        self._close_report(rep, dur)

    def _maintenance(self, eq: Equipment, area: Area, in_shift: bool):
        m = eq.tcfg["maintenance"]
        t0 = self.now
        self._stop(eq, area, "maintenance", "planned_maintenance", "Плановое ТО", True)
        rep = self._open_report(eq, "planned_maintenance", "плановое ТО", t0, "Плановое ТО")
        dur = float(m["duration_min"])
        yield self.env.timeout(dur)
        eq.since_to_h = 0.0
        eq.to_due = False
        eq.last_to_t = self.now
        if m.get("renews_wear", True):
            for mode in eq.modes:
                if mode.wear:
                    eq.renew_mode(mode)
            if eq.tcfg.get("filter"):
                eq.renew_filter()
        self._resume(eq, area)
        self._close_report(rep, dur)

    # ── отчёты рабочих ──

    def _open_report(self, eq: Equipment, reason: str, subtype: str, t0: float, reason_text: str) -> dict:
        self._report_seq += 1
        rep = {
            "id": f"R-{self._report_seq:06d}", "equipment_id": eq.id, "area_id": eq.area_id,
            "t_start": t0, "t_end": None, "source": "machine", "status": "draft",
            "reason": "", "true_reason": reason, "true_subtype": subtype, "machine_reason_text": reason_text,
            "description": "", "actions_taken": "", "reporter_role": "",
        }
        self.rec.report_open(rep)
        return rep

    def _close_report(self, rep: dict, duration: float) -> None:
        eq = self.equipment[rep["equipment_id"]]
        if eq.id in self.manual_reports:          # черновик останется — его заполнит рабочий в интерфейсе
            self.manual_reports.discard(eq.id)
            rep.update(t_end=rep["t_start"] + duration)
            self.rec.report_close(rep)
            return
        text = make_report_text(rep["true_subtype"], eq.name, rep["true_reason"], eq.rng)
        rep.update(
            t_end=rep["t_start"] + duration,
            source="operator_form" if text["completed"] else "machine",
            status="completed" if text["completed"] else "draft",
            reason=text["reason"] if text["completed"] else "",
            description=text["description"], actions_taken=text["actions_taken"],
            reporter_role=text["reporter_role"],
        )
        self.rec.report_close(rep)

    # ── управление и сценарии ──

    def run_until(self, t_min: float) -> None:
        self.env.run(until=t_min)

    def run_days(self, days: float) -> None:
        self.run_until(self.now + days * DAY_MIN)

    def schedule_failure(self, equipment_id: str, mode_id: str, in_op_min: float, lead_min: float | None = None) -> None:
        """Сценарий: отказ через `in_op_min` минут работы, с предвестником длиной `lead_min`."""
        eq = self.equipment[equipment_id]
        mode = next(m for m in eq.modes if m.cfg["id"] == mode_id)
        mode.ttf_h = mode.age_h + in_op_min / 60.0
        if lead_min is not None:
            mode.lead_h = lead_min / 60.0

    def set_filter_remaining(self, equipment_id: str, remaining_h: float) -> None:
        """Сценарий: фильтр камеры засорится через `remaining_h` моточасов."""
        eq = self.equipment[equipment_id]
        eq.filter_life_h = eq.filter_age_h + remaining_h

    def maintenance_status(self) -> list[dict]:
        out = []
        for eq in self.equipment.values():
            out.append({
                "equipment_id": eq.id, "interval_h": eq.interval_h,
                "hours_since": round(eq.since_to_h, 1),
                "hours_left": round(max(0.0, eq.interval_h - eq.since_to_h), 1),
                "due": eq.to_due,
            })
        return out
