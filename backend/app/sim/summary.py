"""Сводки по результатам симуляции: таблицы событий и агрегаты по сменам.

Агрегаты по сменам считаются так же, как в тестовых данных организаторов:
факт = все выпущенные кузова (вместе с браком), время работы = время в состоянии «работает».
"""

from __future__ import annotations

from datetime import timedelta, timezone

import numpy as np
import pandas as pd

from app.sim.engine import PlantSim

TZ = timezone(timedelta(hours=5))
STATES = ["running", "down", "maintenance", "setup", "starved", "blocked"]


def _ts(sim: PlantSim, t: np.ndarray | pd.Series) -> pd.Series:
    base = pd.Timestamp(sim.cal.start).tz_localize(TZ)
    return base + pd.to_timedelta(np.asarray(t, dtype=float), unit="m")


def frames(sim: PlantSim) -> dict[str, pd.DataFrame]:
    """Все записи модели в виде таблиц с настоящими датами (UTC+5)."""
    rec = sim.rec
    ev = pd.DataFrame(rec.events, columns=["t", "scope", "id", "area_id", "state", "reason", "reason_text", "planned"])
    tel = pd.DataFrame(rec.telemetry, columns=["t", "equipment_id", "temperature", "vibration", "current",
                                               "cycle_time", "filter_dp"])
    units = pd.DataFrame(rec.units, columns=["t", "unit_id", "model", "area_id", "defect_code"])
    reports = pd.DataFrame(rec.reports)
    for df in (ev, tel, units):
        df.insert(0, "ts", _ts(sim, df["t"]) if len(df) else pd.Series(dtype="datetime64[ns, UTC+05:00]"))
    units["result"] = np.where(units["defect_code"] == "", "ok", "defect")
    if len(reports):
        reports["ts_start"] = _ts(sim, reports["t_start"])
        reports["ts_end"] = _ts(sim, reports["t_end"])
        reports["duration_min"] = (reports["t_end"] - reports["t_start"]).round(1)
    return {"events": ev, "telemetry": tel, "units": units, "reports": reports}


def _intervals(events: list[tuple], area_id: str, t_end: float) -> list[tuple[float, float, str]]:
    rows = [(e[0], e[4]) for e in events if e[1] == "area" and e[2] == area_id]
    out = []
    for (t0, st), (t1, _) in zip(rows, rows[1:] + [(t_end, "")]):
        if t1 > t0:
            out.append((t0, t1, st))
    return out


def shift_summary(sim: PlantSim) -> pd.DataFrame:
    """Таблица «смена × участок»: план, факт, брак, время работы и потерь, зарегистрированные простои."""
    plan = int(sim.plant["rates"]["plan_units_per_shift"])
    windows = sim.cal.shift_windows(0.0, sim.now)
    rows = []

    unit_shift: dict[tuple[int, int, str], list[int]] = {}
    for t, _, _, area_id, defect in sim.rec.units:
        s = sim.cal.shift_at(t - 1e-9)
        if s:
            k = (s[0], s[1], area_id)
            acc = unit_shift.setdefault(k, [0, 0])
            acc[0] += 1
            acc[1] += defect != ""

    # Зарегистрированные простои = длительность отчётов (кроме микроостановок), пересечённая со сменой.
    reps = [(r["area_id"], r["t_start"], r["t_end"]) for r in sim.rec.reports if r["true_reason"] != "other"]

    for area_id, area in sim.areas.items():
        if area.proc is None:
            continue
        ints = _intervals(sim.rec.events, area_id, sim.now)
        i = 0
        for day, sid, a, b in windows:
            mins = dict.fromkeys(STATES, 0.0)
            while i < len(ints) and ints[i][1] <= a:
                i += 1
            j = i
            while j < len(ints) and ints[j][0] < b:
                t0, t1, st = ints[j]
                ov = min(t1, b) - max(t0, a)
                if ov > 0 and st in mins:
                    mins[st] += ov
                j += 1
            reg = sum(max(0.0, min(e, b) - max(s, a)) for ar, s, e in reps if ar == area_id)
            fact, defects = unit_shift.get((day, sid, area_id), [0, 0])
            lost = (b - a) - mins["running"]
            rows.append({
                "date": (sim.cal.start + timedelta(days=day)).date(), "shift": sid, "area_id": area_id,
                "plan_units": plan, "fact_units": fact, "defects": defects,
                "defect_rate": defects / fact if fact else 0.0,
                "run_h": mins["running"] / 60.0,
                **{f"{k}_min": round(v, 1) for k, v in mins.items() if k != "running"},
                "lost_min": round(lost, 1), "registered_min": round(reg, 1),
            })
    return pd.DataFrame(rows)


def calibration_report(summary: pd.DataFrame) -> pd.DataFrame:
    """Средние по участкам — для сверки с тестовыми данными организаторов."""
    g = summary.groupby("area_id")
    return pd.DataFrame({
        "смен": g.size(),
        "факт_ср": g["fact_units"].mean().round(1),
        "факт_мин": g["fact_units"].min(),
        "факт_макс": g["fact_units"].max(),
        "работа_ч_ср": g["run_h"].mean().round(2),
        "брак_%": (g["defects"].sum() / g["fact_units"].sum() * 100).round(2),
        "простой_зарег_мин_ср": g["registered_min"].mean().round(1),
    })
