"""ИИ: клиент LLM (Groq/Gemini) без сети, классификатор отчётов, прогноз отказов, выводы, API."""

import json

import httpx
import numpy as np
import pytest

from app.assistant.insights import numbers_ok
from app.assistant.llm import LLMClient, LLMError, parse_json
from app.ml.failure import FEATURES, AlertLogic, FailureModel, compute_features
from app.ml.forecast import bootstrap_month
from app.ml.report_classifier import classify, rules_predict


# ─────────────────────────────── LLM-клиент ───────────────────────────────────


def _client(tmp_path, handler, monkeypatch, **env):
    for k in ("GROQ_API_KEY", "GEMINI_API_KEY", "GROQ_MODEL", "GEMINI_MODEL", "ALLUR_LLM_ORDER"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ALLUR_LLM_PROVIDER", "auto")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return LLMClient(cache_dir=tmp_path, transport=httpx.MockTransport(handler))


def test_llm_without_keys_raises(tmp_path, monkeypatch):
    c = _client(tmp_path, lambda r: httpx.Response(500), monkeypatch)
    assert not c.available
    with pytest.raises(LLMError, match="нет ключа"):
        c.complete_json("t", "sys", "user")


def test_groq_request_and_cache(tmp_path, monkeypatch):
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        body = json.loads(req.content)
        assert req.url.host == "api.groq.com"
        assert req.headers["authorization"] == "Bearer gsk_test"
        assert body["response_format"] == {"type": "json_object"}
        assert body["messages"][0]["role"] == "system"
        return httpx.Response(200, json={"choices": [{"message": {"content": '```json\n{"ok": 1}\n```'}}]})

    c = _client(tmp_path, handler, monkeypatch, GROQ_API_KEY="gsk_test", GROQ_MODEL="llama-3.3-70b-versatile")
    r = c.complete_json("t", "sys", "user")
    assert r.data == {"ok": 1} and r.provider == "groq" and not r.cached
    r2 = c.complete_json("t", "sys", "user")          # второй раз — из кэша, без сети
    assert r2.cached and len(seen) == 1
    assert c.status()["cache_entries"] == 1


def test_fallback_groq_rate_limit_to_gemini(tmp_path, monkeypatch):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "api.groq.com":
            return httpx.Response(429, json={"error": {"message": "rate limit"}})
        assert req.headers["x-goog-api-key"] == "AIza_test"
        assert "gemini-x" in req.url.path
        body = json.loads(req.content)
        assert body["generationConfig"]["responseMimeType"] == "application/json"
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [
            {"text": "размышление", "thought": True}, {"text": '{"answer": "да"}'}]}}]})

    c = _client(tmp_path, handler, monkeypatch, GROQ_API_KEY="gsk", GEMINI_API_KEY="AIza_test", GEMINI_MODEL="gemini-x")
    r = c.complete_json("t", "s", "u", use_cache=False)
    assert r.provider == "gemini" and r.data == {"answer": "да"}


def test_bad_key_disables_provider(tmp_path, monkeypatch):
    c = _client(tmp_path, lambda r: httpx.Response(401, json={"error": {"message": "Invalid API Key"}}),
                monkeypatch, GROQ_API_KEY="bad")
    with pytest.raises(LLMError):
        c.complete_json("t", "s", "u")
    assert not c.available
    assert "401" in c.status()["providers"][0]["disabled_reason"]


def test_parse_json_variants():
    assert parse_json('Вот ответ: {"a": [1, 2]} — готово') == {"a": [1, 2]}
    with pytest.raises(Exception):
        parse_json("не json")


def test_number_guard():
    allowed = {8.3, 2.4, 1752.0, 300.0}
    assert numbers_ok("Брак 8,3% против 2,4% при перепаде 300 Па, 1 752 кузова", allowed)
    assert not numbers_ok("Брак вырастет до 17,5%", allowed)


# ─────────────────────────────── локальные модели ─────────────────────────────


def test_report_classifier():
    p = classify("конвейер дёргается, цепь гремит, потом обрыв")
    assert p.subtype == "цепь" and p.reason == "breakdown" and p.confidence > 0.5
    assert classify("перепад на фильтре в красной зоне, сорность").reason == "consumables"
    assert rules_predict("ТО по графику") .reason == "planned_maintenance"
    assert classify("") is None


def test_failure_features_and_alert_logic():
    base = {"temperature": [40.0, 0.8], "vibration": [2.0, 0.18], "current": [12.0, 0.35]}
    rows = np.array([[i, 40.0, 2.0, 12.0] for i in range(60)], dtype=float)
    x = compute_features(rows, base, 0.5, False)
    assert len(x) == len(FEATURES) and abs(x[0]) < 1e-9
    rows[-15:, 3] = 13.2     # ток +10%
    assert compute_features(rows, base, 0.5, False)[0] == pytest.approx(0.1)
    a = AlertLogic(0.7, 0.35, 2)
    assert [a.update(p) for p in (0.8, 0.9, 0.5, 0.2)] == [None, "open", None, "close"]


def test_failure_model_shipped():
    """Модель прогноза отказов лежит в репозитории (текстовый формат LightGBM) и даёт высокий риск на предвестнике."""
    m = FailureModel.load()
    assert m is not None and m.method("conveyor") == "ml" and m.method("oven") == "rule"
    calm = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.3, 0.0])
    wear = np.array([0.12, 0.06, 0.9, 0.5, 0.02, 0.1, 1.0, 0.8, 0.0])
    assert m.score("conveyor", wear) > m.score("conveyor", calm) + 0.3


def test_bootstrap_month():
    rng = np.random.default_rng(0)
    hist = list(rng.normal(116, 3, 40))
    rem = [(f"d{i // 2}", 1.0) for i in range(20)]
    f = bootstrap_month(2500, hist, rem, 5500, n_sims=2000)
    assert f["p10"] <= f["p50"] <= f["p90"]
    assert 2500 + 20 * 110 < f["p50"] < 2500 + 20 * 122
    assert f["prob_target"] == 0.0 and f["required_per_shift"] == pytest.approx(150, abs=0.1)
    assert len(f["band"]) == 10 and f["band"][-1]["p50"] == pytest.approx(f["p50"], abs=2)


def test_llm_rewrite_guard():
    """LLM переписывает текст выводов; выдуманные числа отбрасываются, эффект остаётся из расчёта."""
    from app.assistant.insights import llm_rewrite
    from app.assistant.llm import LLMResult

    items = [
        {"id": "a", "severity": "critical", "title": "Брак 8,3%", "summary": "Брак 8,3% против 2,4%.",
         "evidence": ["1752 кузова"], "recommendation": "Менять фильтр при 300 Па.",
         "effect": {"cars_month": 50, "text": "до +50 авто"}, "rank": 1},
        {"id": "b", "severity": "info", "title": "ТО", "summary": "16 ТО, 500 мин.", "evidence": [],
         "recommendation": "Ночью.", "effect": {"cars_month": 125, "text": "до +125 авто"}, "rank": 2},
    ]
    facts = {"period": {"from": "2026-09-05", "to": "2026-10-05", "workdays": 20}, "loss_by_area": {"Сварка": 957.0}}

    class Stub:
        def complete_json(self, task, system, user, max_tokens=0, use_cache=True):
            return LLMResult({"summary": "Главное — фильтры: брак 8,3% против 2,4%.",
                              "items": [{"id": "a", "title": "Фильтры портят окраску",
                                         "summary": "При 300 Па брак 8,3%, при чистых — 2,4%.",
                                         "recommendation": "Менять ночью при 300 Па."},
                                        {"id": "b", "title": "ТО ночью", "summary": "Потери 777 мин в месяц.",
                                         "recommendation": "Перенести ТО ночью."}],
                              "order": ["b", "a"]}, "groq", "test-model")

    summary, out, meta = llm_rewrite(Stub(), items, facts, None)
    assert summary.startswith("Главное")
    by = {i["id"]: i for i in out}
    assert by["a"]["source"] == "llm" and by["a"]["title"] == "Фильтры портят окраску"
    assert by["b"]["source"] == "rules" and by["b"]["summary"] == "16 ТО, 500 мин."   # 777 — выдумано
    assert [i["id"] for i in out] == ["b", "a"] and meta["rejected_by_guard"] == 1
    assert by["a"]["effect"]["cars_month"] == 50
