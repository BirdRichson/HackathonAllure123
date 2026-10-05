"""Конфиги согласованы между собой и с тестовыми данными организаторов."""

import csv

from app.config import TEST_DATA_DIR, plant_config, reasons_config


def _rows(name: str) -> list[dict[str, str]]:
    with open(TEST_DATA_DIR / name, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_equipment_areas_exist():
    plant = plant_config()
    area_ids = {a["id"] for a in plant["areas"]}
    assert set(plant["flow"]) == area_ids
    for eq in plant["equipment"]:
        assert eq["area"] in area_ids, eq


def test_equipment_ids_unique():
    ids = [eq["id"] for eq in plant_config()["equipment"]]
    assert len(ids) == len(set(ids))


def test_downtime_equipment_known():
    names = {eq["name"] for eq in plant_config()["equipment"]}
    for row in _rows("downtime.csv"):
        assert row["equipment"] in names, row


def test_downtime_reasons_mapped():
    reasons = reasons_config()
    for row in _rows("downtime.csv"):
        mapped = reasons["mapping"][row["reason_text"]]
        assert mapped["code"] in reasons["codes"]


def test_lines_match_areas():
    lines = {a["line_id"]: a["name"] for a in plant_config()["areas"] if a["line_id"]}
    for row in _rows("lines.csv"):
        assert lines[row["line_id"]] == row["area"]


def test_models_match_plan():
    plan = {r["model"]: int(r["plan_month_units"]) for r in _rows("plan_models.csv")}
    models = {m["name"]: m["plan_month_units"] for m in plant_config()["models"]}
    assert plan == models
