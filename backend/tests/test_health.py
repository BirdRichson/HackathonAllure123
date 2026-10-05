from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_ok():
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["data_mode"] in {"demo", "plant"}
    assert body["time"].endswith("+05:00")


def test_targets_from_test_data():
    t = client.get("/api/targets").json()
    assert t["oee_min"] == 0.85
    assert t["defect_rate_max"] == 0.02
    assert t["critical_downtime_max_min_per_day"] == 60
    assert t["monthly_output_min"] == 5500


def test_plant_flow():
    p = client.get("/api/plant").json()
    assert p["flow"] == ["WH", "WELD", "PAINT", "ASSY", "QC", "FG"]
