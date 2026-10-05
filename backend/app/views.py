"""Представления для API и живого потока: снимок завода, KPI, страница цеха, карточка оборудования.

Все функции принимают Runtime и только читают состояние — ничего не меняют.
"""

from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from app.config import plant_config, targets_config
from app.kpi.engine import MAIN_AREAS, area_kpi, plant_kpi, round_kpi
from app.sim.engine import DAY_MIN

if TYPE_CHECKING:
    from app.runtime import Outbox, Runtime

SHIFT_MIN = 480.0
OP_SHARE = 0.94          # доля смены, когда оборудование реально наращивает моточасы (для оценки даты ТО)


# ─────────────────────────────── смены ────────────────────────────────────────


def shift_window(sim, t: float | None = None) -> dict:
    """Текущая смена, а вне смен — последняя завершённая."""
    t = sim.now if t is None else t
    cal = sim.cal
    s = cal.shift_at(t)
    if s:
        start = cal.shift_end(t) - SHIFT_MIN
        return {"day": s[0], "id": s[1], "start": start, "end": start + SHIFT_MIN, "in_shift": True}
    for back in range(1, 10 * 24 * 4):
        probe = t - back * 15
        s = cal.shift_at(probe)
        if s:
            end = cal.shift_end(probe)
            return {"day": s[0], "id": s[1], "start": end - SHIFT_MIN, "end": end, "in_shift": False}
    return {"day": 0, "id": 1, "start": 0.0, "end": SHIFT_MIN, "in_shift": False}


def shift_info(rt: "Runtime") -> dict:
    w = rt.world
    sw = shift_window(w.sim)
    return {"id": sw["id"], "start": w.iso(sw["start"]), "end": w.iso(sw["end"]), "in_shift": sw["in_shift"],
            "date": w.sim.cal.dt(sw["start"]).date().isoformat()}


# ─────────────────────────────── KPI ──────────────────────────────────────────


def _kpis(sim, t0: float, t1: float) -> dict[str, dict]:
    planned = max(t1 - t0, 1e-6)
    plan = float(plant_config()["rates"]["plan_units_per_shift"]) * planned / SHIFT_MIN
    return {a: area_kpi(sim, a, t0, t1, planned, plan) for a in (*MAIN_AREAS, "QC")}


def _rounded(kpis: dict[str, dict]) -> dict:
    areas = {a: round_kpi(k) for a, k in kpis.items()}
    plant = round_kpi(plant_kpi(kpis))
    return {"areas": areas, "plant": plant}


def finished_units(sim, t0: float, t1: float) -> int:
    units = sim.rec.units
    i = bisect_left(units, (t0,))
    n = 0
    for row in units[i:]:
        if row[0] >= t1:
            break
        n += row[3] == "QC"
    return n


def month_progress(rt: "Runtime") -> dict:
    """Выпуск с начала месяца против цели 5500 — исходные данные для прогноза месяца (этап 4)."""
    w = rt.world
    sim = w.sim
    cal = sim.cal
    now_dt = cal.dt(sim.now)
    month_start = now_dt.replace(day=1, hour=0, minute=0)
    t_month = max(0.0, (month_start - cal.start).total_seconds() / 60)
    out = finished_units(sim, t_month, sim.now)
    plan_shift = float(plant_config()["rates"]["plan_units_per_shift"])
    shifts_done = 0.0
    for _, _, a, b in cal.shift_windows(t_month, sim.now + DAY_MIN):
        if a < sim.now:
            shifts_done += min(1.0, (sim.now - a) / (b - a))
    # Рабочих смен в месяце
    next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
    t_next = (next_month - cal.start).total_seconds() / 60
    shifts_total = len(cal.shift_windows(t_month, t_next))
    return {
        "month": month_start.strftime("%Y-%m"),
        "output_mtd": out,
        "plan_mtd": round(plan_shift * shifts_done),
        "target_month": int(targets_config()["monthly_output_min"]),
        "shifts_done": round(shifts_done, 2),
        "shifts_total": shifts_total,
        "partial_history": t_month == 0.0 and month_start < cal.start,
    }


def kpi_now(rt: "Runtime") -> dict:
    w = rt.world
    sim = w.sim
    sw = shift_window(sim)
    t1 = min(sim.now, sw["end"])
    shift = _rounded(_kpis(sim, sw["start"], t1))
    day_start = sw["day"] * DAY_MIN + min(s0 for _, s0, _ in sim.cal.shifts)
    day = _rounded(_kpis(sim, day_start, t1))
    return {
        "sim_time": w.iso(sim.now),
        "shift": {**shift_info(rt), **shift, "output": finished_units(sim, sw["start"], t1)},
        "day": {**day, "output": finished_units(sim, day_start, t1),
                "plan": round(float(plant_config()["rates"]["plan_units_per_shift"]) * (t1 - day_start) / SHIFT_MIN)},
        "month": month_progress(rt),
        "targets": targets_config(),
    }


def shift_history(rt: "Runtime", area_id: str, n: int = 12) -> list[dict]:
    w = rt.world
    sim = w.sim
    sw = shift_window(sim)
    windows = [x for x in sim.cal.shift_windows(max(0.0, sim.now - 20 * DAY_MIN), sim.now) if x[3] <= sw["start"] + 1e-6]
    plan = float(plant_config()["rates"]["plan_units_per_shift"])
    out = []
    for day, sid, a, b in windows[-n:]:
        k = round_kpi(area_kpi(sim, area_id, a, b, b - a, plan))
        out.append({"date": sim.cal.dt(a).date().isoformat(), "shift": sid, "oee": k["oee"],
                    "availability": k["availability"], "performance": k["performance"], "quality": k["quality"],
                    "defect_rate": k["defect_rate"], "fact_units": k["fact_units"], "run_min": k["run_min"]})
    return out


# ─────────────────────────────── состояния ────────────────────────────────────


def area_state(area) -> dict:
    state, reason, text = area.last_key or (area.state, "", "")
    return {"state": state, "reason": reason, "reason_text": text}


def equipment_state(sim, eq) -> dict:
    if eq.status != "ok":
        info = sim.areas[eq.area_id].blockers.get(eq.id)
        return {"state": eq.status, "reason": info[1] if info else "", "reason_text": info[2] if info else ""}
    a = area_state(sim.areas[eq.area_id])
    if a["state"] in ("down", "maintenance"):
        # участок стоит из-за другого оборудования — этот станок простаивает
        return {"state": "idle", "reason": a["reason"], "reason_text": f"Участок остановлен: {a['reason_text']}"}
    return a


def telemetry_dict(row: tuple | None, world) -> dict | None:
    if row is None:
        return None
    return {"ts": world.iso(row[0]), "temperature": row[2], "vibration": row[3], "current": row[4],
            "cycle_time": row[5], "filter_dp": row[6]}


def _estimate_due(sim, hours_left: float) -> float | None:
    remaining = hours_left * 60
    for _, _, a, b in sim.cal.shift_windows(sim.now - SHIFT_MIN, sim.now + 60 * DAY_MIN):
        if b <= sim.now:
            continue
        a = max(a, sim.now)
        avail = (b - a) * OP_SHARE
        if avail >= remaining:
            return a + remaining / OP_SHARE
        remaining -= avail
    return None


def maintenance(rt: "Runtime", eq_ids: list[str] | None = None) -> list[dict]:
    w = rt.world
    sim = w.sim
    out = []
    for eq in sim.equipment.values():
        if eq_ids and eq.id not in eq_ids:
            continue
        left = max(0.0, eq.interval_h - eq.since_to_h)
        due_t = sim.now if eq.to_due else _estimate_due(sim, left)
        m = eq.tcfg["maintenance"]
        out.append({
            "equipment_id": eq.id, "name": eq.name, "interval_h": eq.interval_h,
            "hours_since": round(eq.since_to_h, 1), "hours_left": round(left, 1),
            "progress": round(min(1.0, eq.since_to_h / eq.interval_h), 3),
            "due": eq.to_due, "duration_min": m["duration_min"],
            "last_done_ts": w.iso(eq.last_to_t), "next_due_ts": w.iso(due_t),
            "window": sim.window,
        })
    return out


def areas_brief(rt: "Runtime") -> list[dict]:
    sim = rt.world.sim
    plant = plant_config()
    out = []
    for a in plant["areas"]:
        area = sim.areas[a["id"]]
        item = {"id": a["id"], "name": a["name"], "line_id": a.get("line_id"), **area_state(area)}
        if area.in_buf is not None:
            item["buffer_in"] = {"count": len(area.in_buf), "capacity": area.in_cap}
        if a["id"] == sim.first_area:
            item["stock"] = sim.wh_stock
        out.append(item)
    return out


def equipment_brief(rt: "Runtime") -> list[dict]:
    w = rt.world
    sim = w.sim
    mt = {m["equipment_id"]: m for m in maintenance(rt)}
    out = []
    for e in plant_config()["equipment"]:
        eq = sim.equipment[e["id"]]
        out.append({"id": eq.id, "name": eq.name, "area_id": eq.area_id, "type": eq.type,
                    "critical": e["critical"], "source": e["source"], **equipment_state(sim, eq),
                    "telemetry": telemetry_dict(sim.rec.last_telemetry.get(eq.id), w),
                    "maintenance": mt[eq.id]})
    return out


# ─────────────────────────────── простои ──────────────────────────────────────

FLOW_TEXT = {"starved": "Нет входа", "blocked": "Выход занят"}


def stop_intervals(sim, t0: float, t1: float) -> list[dict]:
    """Остановки за период: поломки, замены, ТО (по оборудованию), микроостановки, переналадки, ожидание."""
    events = sim.rec.events
    i = bisect_left(events, (t0,))
    open_eq: dict[str, tuple] = {}
    open_area: dict[str, tuple] = {}
    out = []

    def close_area(area_id: str, t: float) -> None:
        st = open_area.pop(area_id, None)
        if st and t > st[0]:
            ts, state, reason, text, planned = st
            kind = "micro" if text == "Микроостановка" else ("setup" if state == "setup" else "flow")
            out.append({"equipment_id": None, "area_id": area_id, "state": state, "reason": reason,
                        "reason_text": text or FLOW_TEXT.get(state, state), "planned": planned, "kind": kind,
                        "start": ts, "end": t})

    for e in events[i:]:
        t, scope, eid, area_id, state, reason, text, planned = e
        if t >= t1:
            break
        if scope == "equipment":
            if state in ("down", "maintenance"):
                open_eq[eid] = (t, state, reason, text, planned, area_id)
            elif eid in open_eq:
                ts, st, rs, tx, pl, ar = open_eq.pop(eid)
                out.append({"equipment_id": eid, "area_id": ar, "state": st, "reason": rs, "reason_text": tx,
                            "planned": pl, "kind": "planned" if pl else "equipment", "start": ts, "end": t})
        else:
            close_area(area_id, t)
            if state == "setup" or state in FLOW_TEXT or (state == "down" and text == "Микроостановка"):
                open_area[area_id] = (t, state, reason, text, planned)
    for eid, (ts, st, rs, tx, pl, ar) in open_eq.items():
        out.append({"equipment_id": eid, "area_id": ar, "state": st, "reason": rs, "reason_text": tx,
                    "planned": pl, "kind": "planned" if pl else "equipment", "start": ts, "end": t1, "ongoing": True})
    for area_id in list(open_area):
        close_area(area_id, t1)
    return out


def _in_shift_minutes(sim, a: float, b: float) -> float:
    """Минуты интервала, пришедшиеся на рабочие смены (ночью ожидание не считается)."""
    total = 0.0
    for _, _, s0, s1 in sim.cal.shift_windows(a - DAY_MIN, b + DAY_MIN):
        total += max(0.0, min(b, s1) - max(a, s0))
    return total


def pareto(rt: "Runtime", area_id: str | None, days: float = 30) -> dict:
    sim = rt.world.sim
    names = {e["id"]: e["name"] for e in plant_config()["equipment"]}
    t0 = max(0.0, sim.now - days * DAY_MIN)
    by_reason: dict[str, dict] = defaultdict(lambda: {"minutes": 0.0, "count": 0, "planned": False, "kind": ""})
    by_eq: dict[str, dict] = defaultdict(lambda: {"minutes": 0.0, "count": 0})
    for s in stop_intervals(sim, t0, sim.now):
        if area_id and s["area_id"] != area_id:
            continue
        mins = _in_shift_minutes(sim, s["start"], s["end"]) if s["kind"] == "flow" else s["end"] - s["start"]
        if mins <= 0:
            continue
        r = by_reason[s["reason_text"]]
        r["minutes"] += mins
        r["count"] += 1
        r["planned"] = s["planned"]
        r["kind"] = s["kind"]
        if s["equipment_id"]:
            e = by_eq[s["equipment_id"]]
            e["minutes"] += mins
            e["count"] += 1
    reasons = sorted(({"reason_text": k, **{kk: (round(vv, 1) if isinstance(vv, float) else vv)
                                              for kk, vv in v.items()}} for k, v in by_reason.items()),
                     key=lambda x: -x["minutes"])
    total = sum(r["minutes"] for r in reasons) or 1.0
    acc = 0.0
    for r in reasons:
        acc += r["minutes"]
        r["share"] = round(r["minutes"] / total, 4)
        r["cumulative"] = round(acc / total, 4)
    equipment = sorted(({"equipment_id": k, "name": names.get(k, k), "minutes": round(v["minutes"], 1),
                         "count": v["count"]} for k, v in by_eq.items()), key=lambda x: -x["minutes"])
    return {"days": days, "reasons": reasons, "equipment": equipment}


# ─────────────────────────────── снимок и живой поток ─────────────────────────


def snapshot(rt: "Runtime") -> dict:
    return {
        **rt.status(),
        "shift": shift_info(rt),
        "areas": areas_brief(rt),
        "equipment": equipment_brief(rt),
        "kpi": kpi_now(rt),
        "incidents": rt.db.list_incidents(status="open", limit=30),
        "recent_incidents": rt.db.list_incidents(limit=30),
        "reports": rt.db.list_reports(limit=20),
    }


def _event(world, e: tuple) -> dict:
    t, scope, eid, area_id, state, reason, text, planned = e
    return {"ts": world.iso(t), "scope": scope, "id": eid, "area_id": area_id, "state": state,
            "reason": reason, "reason_text": text, "planned": planned}


def tick_payload(rt: "Runtime", out: "Outbox", incidents: list[dict]) -> dict:
    w = rt.world
    return {
        **rt.status(),
        "areas": areas_brief(rt),
        "equipment": [{"id": e["id"], "state": e["state"], "reason_text": e["reason_text"],
                       "telemetry": e["telemetry"]} for e in equipment_brief(rt)],
        "events": [_event(w, e) for e in out.events],
        "units": [{"ts": w.iso(u[0]), "unit_id": u[1], "model": u[2], "area_id": u[3], "defect": u[4]}
                  for u in out.units],
        "reports": list(out.reports.values()),
        "incidents": [{k: v for k, v in i.items() if k != "key"} for i in incidents],
    }


# ─────────────────────────────── цех и оборудование ───────────────────────────


def area_view(rt: "Runtime", area_id: str) -> dict | None:
    sim = rt.world.sim
    if area_id not in sim.areas:
        return None
    a_cfg = next(a for a in plant_config()["areas"] if a["id"] == area_id)
    eq_ids = [e.id for e in sim.areas[area_id].equipment]
    kpi = kpi_now(rt)
    return {
        "area": {**next(a for a in areas_brief(rt) if a["id"] == area_id), "source": a_cfg["source"]},
        "equipment": [e for e in equipment_brief(rt) if e["id"] in eq_ids],
        "kpi": {"shift": kpi["shift"]["areas"].get(area_id), "day": kpi["day"]["areas"].get(area_id),
                "history": shift_history(rt, area_id) if area_id in (*MAIN_AREAS, "QC") else []},
        "pareto": pareto(rt, area_id),
        "reports": rt.db.list_reports(area=area_id, limit=15),
        "incidents": rt.db.list_incidents(area=area_id, limit=15),
        "targets": targets_config(),
        "shift": shift_info(rt),
    }


def equipment_view(rt: "Runtime", eq_id: str, hours: float = 8) -> dict | None:
    w = rt.world
    sim = w.sim
    if eq_id not in sim.equipment:
        return None
    brief = next(e for e in equipment_brief(rt) if e["id"] == eq_id)
    t0 = sim.now - hours * 60
    rows = [r for r in sim.rec.telemetry if r[1] == eq_id and r[0] >= t0]
    step = max(1, len(rows) // 600)
    rows = rows[::step]
    series = {"ts": [w.iso(r[0]) for r in rows], "temperature": [r[2] for r in rows],
              "vibration": [r[3] for r in rows], "current": [r[4] for r in rows],
              "filter_dp": [r[6] for r in rows] if rows and rows[0][6] is not None else None}
    eq = sim.equipment[eq_id]
    base = eq.tcfg["telemetry"]
    stops = [s for s in stop_intervals(sim, max(0.0, sim.now - 30 * DAY_MIN), sim.now) if s["equipment_id"] == eq_id]
    return {
        **brief,
        "telemetry_series": series,
        "telemetry_norm": {k: {"mean": v[0], "std": v[1]} for k, v in base.items()},
        "filter": eq.tcfg.get("filter"),
        "stops": [{"start": w.iso(s["start"]), "end": w.iso(s["end"]), "minutes": round(s["end"] - s["start"], 1),
                   "reason_text": s["reason_text"], "planned": s["planned"]} for s in stops][-20:],
        "reports": rt.db.list_reports(equipment=eq_id, limit=10),
    }


def reconciliation(rt: "Runtime", days: float = 7) -> list[dict]:
    """По каждой закрытой смене: потеря рабочего времени против записанных простоев оборудования."""
    w = rt.world
    sim = w.sim
    sw = shift_window(sim)
    t_from = max(0.0, sim.now - days * DAY_MIN)
    stops = [s for s in stop_intervals(sim, t_from - DAY_MIN, sim.now) if s["kind"] in ("equipment", "planned")]
    out = []
    for _, sid, a, b in sim.cal.shift_windows(t_from, sw["start"] + 1e-6):
        for area_id in MAIN_AREAS:
            k = area_kpi(sim, area_id, a, b, b - a, 0)
            lost = (b - a) - k["run_min"]
            reg = sum(max(0.0, min(s["end"], b) - max(s["start"], a)) for s in stops if s["area_id"] == area_id)
            out.append({"date": sim.cal.dt(a).date().isoformat(), "shift": sid, "area_id": area_id,
                        "lost_min": round(lost, 1), "registered_min": round(reg, 1),
                        "unregistered_min": round(lost - reg, 1),
                        "breakdown": {k2: v for k2, v in k["lost_min"].items() if v > 0}})
    return out
