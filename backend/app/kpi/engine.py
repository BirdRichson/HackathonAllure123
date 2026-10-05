"""KPI: OEE и производные показатели. Формулы едины для симулятора, данных завода и интерфейса.

A (доступность)      = время работы / плановое время
P (производительность) = идеальный цикл × выпущено / время работы
Q (качество)         = годные / выпущено          (выпущено включает брак — как в данных организаторов)
OEE                  = A × P × Q
"""

from __future__ import annotations

from bisect import bisect_left
from typing import Any

from app.config import plant_config, targets_config

MAIN_AREAS = ("WELD", "PAINT", "ASSY")


def oee(run_min: float, planned_min: float, produced: int, defects: int, ideal_cycle_min: float) -> dict[str, float]:
    """Доступность, производительность, качество и OEE (доли от 0 до 1)."""
    a = run_min / planned_min if planned_min > 0 else 0.0
    p = ideal_cycle_min * produced / run_min if run_min > 0 else 0.0
    q = (produced - defects) / produced if produced > 0 else 1.0
    return {"availability": a, "performance": p, "quality": q, "oee": a * p * q}


def ideal_cycle() -> float:
    return float(plant_config()["rates"]["ideal_cycle_min"])


def targets_ok(k: dict[str, Any]) -> dict[str, bool]:
    t = targets_config()
    return {
        "oee": k.get("oee", 0.0) >= t["oee_min"],
        "defect_rate": k.get("defect_rate", 0.0) <= t["defect_rate_max"],
    }


def oee_level(value: float) -> str:
    """ok / warn / bad — цвет по порогам из targets.yaml."""
    t = targets_config()
    if value >= t["oee_min"]:
        return "ok"
    return "warn" if value >= t["oee_red_below"] else "bad"


# ───────────────────────── расчёт по записям симулятора ─────────────────────────

STATES = ("running", "down", "maintenance", "setup", "starved", "blocked")


def area_window(sim, area_id: str, t0: float, t1: float) -> dict[str, Any]:
    """Выпуск, брак и минуты по состояниям участка в окне [t0, t1) модельного времени."""
    units = sim.rec.units
    i = bisect_left(units, (t0,))
    produced = defects = 0
    for row in units[i:]:
        if row[0] >= t1:
            break
        if row[3] == area_id:
            produced += 1
            defects += row[4] != ""

    events = sim.rec.events
    j = bisect_left(events, (t0,))
    state = "offline"
    for k in range(j - 1, -1, -1):          # состояние на момент t0
        e = events[k]
        if e[1] == "area" and e[2] == area_id:
            state = e[4]
            break
    mins = dict.fromkeys(STATES, 0.0)
    t_prev = t0
    for e in events[j:]:
        if e[0] >= t1:
            break
        if e[1] == "area" and e[2] == area_id:
            if state in mins:
                mins[state] += e[0] - t_prev
            state, t_prev = e[4], e[0]
    if state in mins:
        mins[state] += t1 - t_prev
    return {"produced": produced, "defects": defects, "minutes": mins}


def area_kpi(sim, area_id: str, t0: float, t1: float, planned_min: float, plan_units: float) -> dict[str, Any]:
    w = area_window(sim, area_id, t0, t1)
    k = oee(w["minutes"]["running"], planned_min, w["produced"], w["defects"], ideal_cycle())
    produced = w["produced"]
    k.update(
        plan_units=round(plan_units, 1),
        fact_units=produced,
        good_units=produced - w["defects"],
        defects=w["defects"],
        defect_rate=w["defects"] / produced if produced else 0.0,
        run_min=round(w["minutes"]["running"], 1),
        planned_min=round(planned_min, 1),
        lost_min={s: round(v, 1) for s, v in w["minutes"].items() if s != "running"},
    )
    k["targets_ok"] = targets_ok(k)
    k["level"] = oee_level(k["oee"])
    return k


def round_kpi(k: dict[str, Any]) -> dict[str, Any]:
    out = dict(k)
    for key in ("availability", "performance", "quality", "oee", "defect_rate"):
        if key in out:
            out[key] = round(out[key], 4)
    return out


def plant_kpi(area_kpis: dict[str, dict]) -> dict[str, Any]:
    """OEE завода — среднее по основным участкам (сварка, окраска, сборка)."""
    vals = [area_kpis[a] for a in MAIN_AREAS if a in area_kpis]
    if not vals:
        return {}
    n = len(vals)
    k = {key: sum(v[key] for v in vals) / n for key in ("availability", "performance", "quality", "oee")}
    k["defect_rate"] = sum(v["defects"] for v in vals) / max(1, sum(v["fact_units"] for v in vals))
    k["targets_ok"] = targets_ok(k)
    k["level"] = oee_level(k["oee"])
    return k
