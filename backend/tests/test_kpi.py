"""KPI-движок воспроизводит эталон из docs/TEST_DATA.md и согласован со сводкой симулятора."""

import pytest

from app.config import ROOT_DIR, plant_config
from app.ingest.organizer import import_files
from app.kpi.engine import area_kpi, oee
from app.sim.engine import PlantSim
from app.sim.summary import shift_summary

# Эталон OEE по тестовым данным (docs/TEST_DATA.md, раздел 2): паспортный цикл 3,8 мин и плановый такт 4 мин.
REFERENCE = {
    ("2026-10-01", "Сварка"): (91.8, 96.7),
    ("2026-10-01", "Окраска"): (87.9, 92.5),
    ("2026-10-01", "Сборка"): (95.0, 100.0),
    ("2026-10-02", "Сварка"): (85.5, 90.0),
    ("2026-10-02", "Окраска"): (87.1, 91.7),
    ("2026-10-02", "Сборка"): (92.6, 97.5),
}


@pytest.fixture(scope="module")
def organizer():
    f = ROOT_DIR / "data" / "raw" / "test_data_2026-10-05.docx"
    return import_files([(f.name, f.read_bytes())])


def test_oee_formula():
    k = oee(run_min=450, planned_min=480, produced=115, defects=4, ideal_cycle_min=3.8)
    assert k["availability"] == pytest.approx(0.9375)
    assert k["performance"] == pytest.approx(3.8 * 115 / 450)
    assert k["quality"] == pytest.approx(111 / 115)
    assert k["oee"] == pytest.approx(k["availability"] * k["performance"] * k["quality"])


def test_reproduces_reference_oee(organizer):
    rows = {(r["date"], r["area"]): r for r in organizer["kpi_rows"]}
    assert set(rows) == set(REFERENCE)
    for key, (ref, ref_takt) in REFERENCE.items():
        assert round(rows[key]["oee"] * 100, 1) == pytest.approx(ref, abs=0.05), key
        assert round(rows[key]["oee_plan_takt"] * 100, 1) == pytest.approx(ref_takt, abs=0.05), key


def test_load_equals_run_time_share(organizer):
    """«Загрузка, %» организаторов = время работы / 8 ч (одна строка отличается на 1 п.п.)."""
    diffs = [abs(r["load_pct"] - r["load_pct_calc"]) for r in organizer["kpi_rows"]]
    assert sum(d < 0.75 for d in diffs) == 5
    assert max(diffs) <= 1.0


def test_area_kpi_matches_shift_summary():
    sim = PlantSim(plant_config(), seed=11)
    sim.run_days(7)
    s = shift_summary(sim)
    row = s[s.area_id == "PAINT"].iloc[3]
    windows = sim.cal.shift_windows(0, sim.now)
    day, sid, a, b = next(w for w in windows if sim.cal.dt(w[2]).date() == row["date"] and w[1] == row["shift"])
    k = area_kpi(sim, "PAINT", a, b, b - a, 120)
    assert k["fact_units"] == row["fact_units"]
    assert k["defects"] == row["defects"]
    assert k["run_min"] / 60 == pytest.approx(row["run_h"], abs=0.01)
