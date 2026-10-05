"""API живого завода: снимок, цех, оборудование, отчёты, управление, WebSocket, импорт."""

import pytest
from fastapi.testclient import TestClient

from app.config import ROOT_DIR

START = "2026-10-05T10:30:00"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setenv("ALLUR_DB_PATH", str(tmp_path_factory.mktemp("db") / "t.db"))
    mp.setenv("ALLUR_NO_LOOP", "1")
    mp.setenv("ALLUR_WARMUP_DAYS", "4")
    mp.setenv("ALLUR_LIVE_START", START)
    from app.main import app
    with TestClient(app) as c:
        yield c
    mp.undo()


def rt(client):
    return client.app.state.runtime


def test_snapshot(client):
    s = client.get("/api/state").json()
    assert s["sim_time"].startswith(START)
    assert s["shift"]["id"] == 1 and s["shift"]["in_shift"]
    assert len(s["areas"]) == 6 and len(s["equipment"]) == 12
    cam = next(e for e in s["equipment"] if e["id"] == "CAM-02")
    assert cam["telemetry"]["filter_dp"] is not None
    assert 0 <= cam["maintenance"]["progress"] <= 1
    k = s["kpi"]
    assert set(k["shift"]["areas"]) == {"WELD", "PAINT", "ASSY", "QC"}
    assert 0 < k["shift"]["plant"]["oee"] <= 1.05
    assert k["month"]["target_month"] == 5500


def test_time_advances_with_speed(client):
    r = rt(client)
    t0 = r.world.sim.now
    client.post("/api/sim/control", json={"speed": 60})
    r.advance(30)                    # 30 с реального времени × 60 = 30 мин модели
    assert r.world.sim.now == pytest.approx(t0 + 30)
    client.post("/api/sim/control", json={"paused": True})
    r.advance(30)
    assert r.world.sim.now == pytest.approx(t0 + 30)
    client.post("/api/sim/control", json={"paused": False, "speed": 10})
    assert client.post("/api/sim/control", json={"speed": 7}).status_code == 400


def test_area_page(client):
    a = client.get("/api/areas/PAINT").json()
    assert a["area"]["name"] == "Окраска"
    assert {e["id"] for e in a["equipment"]} == {"CAM-01", "CAM-02", "OVEN-01"}
    assert all("hours_left" in e["maintenance"] for e in a["equipment"])
    assert a["kpi"]["shift"]["fact_units"] > 0
    assert a["pareto"]["reasons"] and a["pareto"]["reasons"][-1]["cumulative"] == pytest.approx(1.0)
    assert client.get("/api/areas/XXX").status_code == 404


def test_equipment_card(client):
    e = client.get("/api/equipment/CONV-03?hours=4").json()
    assert e["name"] == "Конвейер-03"
    assert len(e["telemetry_series"]["ts"]) > 10
    assert e["telemetry_norm"]["current"]["mean"] == 12.0


def test_worker_report_completes_machine_draft(client):
    r = rt(client)
    sim = r.world.sim
    sim.manual_reports.add("CONV-03")              # отчёт по этой остановке заполнит человек
    sim.schedule_failure("CONV-03", "chain_break", in_op_min=1, lead_min=30)
    r.advance(30)                                   # ×10: 5 мин модели — цепь оборвалась
    import asyncio
    asyncio.run(r.publish())                        # изменения попадают в БД на каждом шаге живого потока
    drafts = client.get("/api/reports?equipment=CONV-03&status=draft").json()
    assert drafts and drafts[0]["machine_reason_text"] == "Обрыв цепи"
    rid = drafts[0]["id"]

    body = {"equipment_id": "CONV-03", "reason": "breakdown", "description": "цепь оборвалась, гремела с утра",
            "actions_taken": "заменили звено", "reporter_role": "наладчик"}
    rep = client.post("/api/reports", json=body).json()
    assert rep["id"] == rid and rep["status"] == "completed"

    r.advance(600)                                  # ремонт закончился — генератор не должен перетереть текст
    asyncio.run(r.publish())
    final = next(x for x in client.get("/api/reports?equipment=CONV-03").json() if x["id"] == rid)
    assert final["description"] == body["description"] and final["ts_end"] is not None
    assert "true_reason" not in final


def test_new_report_and_patch(client):
    rep = client.post("/api/reports", json={"equipment_id": "ABB-02", "reason": "operator",
                                            "description": "ждали кузов", "duration_min": 5,
                                            "complete_draft": False}).json()
    assert rep["id"].startswith("R-U") and rep["source"] == "operator_form"
    p = client.patch(f"/api/reports/{rep['id']}", json={"reason": "other", "description": "ждали кузов, датчик"}).json()
    assert p["reason"] == "other"
    assert client.post("/api/reports", json={"equipment_id": "ABB-02", "reason": "nonsense"}).status_code == 400
    assert client.patch("/api/reports/NOPE", json={"reason": "other"}).status_code == 404


def test_incidents_and_reconciliation(client):
    inc = client.get("/api/incidents").json()
    assert inc and {"id", "title", "severity", "status"} <= set(inc[0])
    rec = client.get("/api/reconciliation?days=4").json()
    assert rec and {"lost_min", "registered_min", "unregistered_min"} <= set(rec[0])


def test_websocket_snapshot(client):
    with client.websocket_connect("/ws/live") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "snapshot" and "areas" in msg["payload"]


def test_ingest_upload_and_latest(client):
    f = ROOT_DIR / "data" / "raw" / "test_data_2026-10-05.docx"
    res = client.post("/api/ingest", files=[("files", (f.name, f.read_bytes(),
                      "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))]).json()
    assert res["rows"]["lines"] == 6
    latest = client.get("/api/ingest/latest").json()
    assert latest["id"] == res["id"] and latest["findings"]
    bad = client.post("/api/ingest", files=[("files", ("x.txt", b"hello", "text/plain"))])
    assert bad.status_code == 422


def test_reset_returns_to_start(client):
    import asyncio
    r = rt(client)
    r.advance(120)
    asyncio.run(r.reset())
    assert r.world.sim.now == pytest.approx((r.settings.start - r.world.sim.cal.start).total_seconds() / 60)


def test_events_window(client):
    e = client.get("/api/events?hours=2&scope=equipment").json()
    assert {x["scope"] for x in e["initial"]} == {"equipment"}
    assert len(e["initial"]) == 12


def test_old_draft_not_hijacked_by_new_report(client):
    """Старый черновик (больше 2 ч назад) не заполняется новым отчётом — создаётся отдельная запись."""
    old = [r for r in client.get("/api/reports?status=draft&limit=200").json()]
    r = rt(client)
    now = r.world.iso(r.world.sim.now)
    stale = next((d for d in old if d["ts_end"] and d["ts_end"] < now[:11] + "00:00:00+05:00"), None)
    if stale is None:
        return
    rep = client.post("/api/reports", json={"equipment_id": stale["equipment_id"], "reason": "breakdown",
                                            "description": "новая поломка"}).json()
    assert rep["id"] != stale["id"]
    explicit = client.post("/api/reports", json={"equipment_id": stale["equipment_id"], "reason": "other",
                                                 "description": "дозаполнил старую", "report_id": stale["id"]}).json()
    assert explicit["id"] == stale["id"] and explicit["status"] == "completed"


def test_scenarios_trigger(client):
    sc = client.get("/api/scenarios").json()
    assert {"sensor_fault", "chain_break", "filter_clog"} <= set(sc)
    r = rt(client)
    assert client.post("/api/scenarios/sensor_fault/trigger").json()["equipment_id"] == "ABB-01"
    client.post("/api/sim/control", json={"speed": 60, "paused": False})
    r.advance(5)
    assert r.world.sim.equipment["ABB-01"].status == "down"
    assert client.post("/api/scenarios/nope/trigger").status_code == 404
    client.post("/api/sim/control", json={"speed": 10})
