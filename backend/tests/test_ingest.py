"""Импорт данных организаторов: docx и csv, цели, находки."""

from app.config import ROOT_DIR
from app.ingest.organizer import import_files


def _docx():
    f = ROOT_DIR / "data" / "raw" / "test_data_2026-10-05.docx"
    return [(f.name, f.read_bytes())]


def test_docx_tables_and_targets():
    r = import_files(_docx())
    assert r["rows"] == {"lines": 6, "downtime": 4, "plan_models": 3, "quality": 6}
    t = r["targets"]
    assert (t["shifts_per_day"], t["shift_hours"]) == (2, 8)
    assert t["oee_min"] == 0.85 and t["defect_rate_max"] == 0.02
    assert t["critical_downtime_max_min_per_day"] == 60 and t["monthly_output_min"] == 5500
    assert r["scheme"][0] == "Склад комплектующих" and r["scheme"][-1] == "Склад готовой продукции"
    q = [x for x in r["tables"]["quality"] if x["area"] == "Окраска"]
    assert [x["defect_pct"] for x in q] == [3.5, 5.2]          # десятичная запятая разобрана


def test_findings_cover_known_problems():
    r = import_files(_docx())
    titles = " | ".join(f["title"] for f in r["findings"])
    assert "Окраска: брак выше нормы 2%" in titles
    assert "Конвейер-03" in titles and "92% лимита" in titles
    assert "4 800" in titles and "5 500" in titles
    assert "Узкое место смещается" in titles
    rec = next(f for f in r["findings"] if f["kind"] == "reconciliation")
    assert any(i["area"] == "Сборка" and i["registered_min"] == 55 and i["lost_min"] == 6 for i in rec["items"])
    assert r["findings"][0]["severity"] == "critical"


def test_downtime_mapped_to_model():
    r = import_files(_docx())
    by_eq = {d["equipment"]: d for d in r["downtime"]}
    assert by_eq["Камера-02"]["equipment_id"] == "CAM-02"
    assert by_eq["Камера-02"]["reason"] == "consumables"
    assert by_eq["ABB-04"]["planned"] is True
    assert not [w for w in r["warnings"] if "нет в модели" in w or "не в справочнике" in w]


def test_csv_import_same_result():
    files = [(p.name, p.read_bytes()) for p in sorted((ROOT_DIR / "data" / "test").glob("*.csv"))]
    r = import_files(files)
    assert r["rows"] == {"downtime": 4, "lines": 6, "plan_models": 3, "quality": 6}
    d = {(k["date"], k["area"]): k["oee"] for k in import_files(_docx())["kpi_rows"]}
    assert {(k["date"], k["area"]): k["oee"] for k in r["kpi_rows"]} == d
