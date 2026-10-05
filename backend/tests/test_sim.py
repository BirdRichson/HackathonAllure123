"""Симулятор: воспроизводимость, калибровка по тестовым данным, предвестники отказов, отчёты рабочих."""

import statistics

import pytest

from app.config import plant_config
from app.sim.engine import PlantSim
from app.sim.summary import shift_summary


def make(days: float, **kw) -> PlantSim:
    sim = PlantSim(plant_config(), **kw)
    sim.run_days(days)
    return sim


@pytest.fixture(scope="module")
def month() -> PlantSim:
    return make(30)


def test_deterministic_by_seed():
    a, b, c = make(4, seed=7), make(4, seed=7), make(4, seed=8)
    assert a.rec.units == b.rec.units
    assert a.rec.events == b.rec.events
    assert a.rec.units != c.rec.units


def test_no_output_outside_shifts(month):
    assert month.rec.units
    for t, *_ in month.rec.units:
        assert month.cal.shift_at(t - 1e-9) is not None


def test_calibrated_to_test_data(month):
    """Ориентиры из тестовых данных: факт 110–121, работа 7,2–8,0 ч, брак сварка ≈2%, окраска ≈4%, сборка ≈1%."""
    s = shift_summary(month)
    for area in ("WELD", "PAINT", "ASSY"):
        a = s[s.area_id == area]
        assert 108 <= a.fact_units.mean() <= 122, area
        assert 7.2 <= a.run_h.mean() <= 8.0, area
    rate = s.groupby("area_id").apply(lambda g: g.defects.sum() / g.fact_units.sum(), include_groups=False)
    assert 0.012 <= rate["WELD"] <= 0.028
    assert 0.030 <= rate["PAINT"] <= 0.055
    assert 0.005 <= rate["ASSY"] <= 0.018
    assert rate["PAINT"] > 0.02 > rate["ASSY"]       # окраска стабильно выше нормы 2%, как в данных

    # Узкое место (меньше всего годных за день) меняется — как 01.10 (окраска) и 02.10 (сварка).
    s["good"] = s.fact_units - s.defects
    daily = s[s.area_id.isin(["WELD", "PAINT", "ASSY"])].groupby(["date", "area_id"]).good.sum().unstack()
    assert daily.idxmin(axis=1).nunique() >= 2


def _failure_time(sim: PlantSim, eq_id: str, text: str) -> float:
    return next(e[0] for e in sim.rec.events if e[1] == "equipment" and e[2] == eq_id and e[6] == text)


def _tele(sim: PlantSim, eq_id: str, t0: float, t1: float, col: int) -> list[float]:
    return [r[col] for r in sim.rec.telemetry if r[1] == eq_id and t0 <= r[0] < t1]


def test_chain_break_has_precursor():
    """Перед обрывом цепи ток и вибрация конвейера растут — на этом учится прогноз отказов."""
    sim = PlantSim(plant_config(), seed=3)
    sim.run_until(3 * 1440 + 8 * 60 + 5)   # вторник, начало первой смены
    t_sched = sim.now
    sim.schedule_failure("CONV-03", "chain_break", in_op_min=200, lead_min=150)
    sim.run_days(1)
    tf = _failure_time(sim, "CONV-03", "Обрыв цепи")
    assert tf > t_sched
    base_cur = statistics.mean(_tele(sim, "CONV-03", t_sched, t_sched + 40, 4))
    base_vib = statistics.mean(_tele(sim, "CONV-03", t_sched, t_sched + 40, 3))
    last_cur = statistics.mean(_tele(sim, "CONV-03", tf - 20, tf, 4))
    last_vib = statistics.mean(_tele(sim, "CONV-03", tf - 20, tf, 3))
    assert last_cur > base_cur * 1.15
    assert last_vib > base_vib * 1.6


def test_filter_clogs_then_replaced():
    sim = PlantSim(plant_config(), seed=5)
    sim.run_until(3 * 1440 + 8 * 60 + 5)
    sim.set_filter_remaining("CAM-02", remaining_h=1.0)
    sim.run_days(1)
    tf = _failure_time(sim, "CAM-02", "Замена фильтра")
    before = _tele(sim, "CAM-02", tf - 10, tf, 6)
    after = _tele(sim, "CAM-02", tf + 45, tf + 120, 6)
    assert statistics.mean(before) > 400       # перед заменой — у предела 450 Па
    assert statistics.mean(after) < 200       # новый фильтр


def test_every_stop_has_worker_report(month):
    stops = [(e[2], e[0]) for e in month.rec.events if e[1] == "equipment" and e[4] in ("down", "maintenance")]
    reports = {(r["equipment_id"], r["t_start"]) for r in month.rec.reports}
    assert stops and all(s in reports for s in stops)

    real = [r for r in month.rec.reports if r["true_reason"] != "other"]
    completed = [r for r in real if r["status"] == "completed"]
    assert len(completed) / len(real) > 0.8
    assert all(r["description"] for r in completed)
    assert any(r["reason"] != r["true_reason"] for r in completed) or len(completed) < 20


def test_night_maintenance_window_moves_to_out_of_shift():
    sim = make(20, maintenance_window="night")
    planned = [r for r in sim.rec.reports if r["true_reason"] == "planned_maintenance"]
    assert planned
    assert all(sim.cal.shift_at(r["t_start"]) is None for r in planned)
