"""ИИ-разбор отчётов рабочих: что случилось по тексту, верно ли выбрана причина, что повторяется.

Каждый заполненный отчёт сразу размечается локальной моделью (быстро, офлайн). Свободный текст,
который рабочий вводит в форме, дополнительно разбирает LLM (Groq/Gemini), если подключён ключ:
она лучше понимает новые формулировки и выделяет узел, который надо проверить.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from app.assistant.llm import LLMClient, LLMError
from app.config import plant_config, reasons_config
from app.ml.report_classifier import (SUBTYPE_LABEL, SUBTYPE_REASON, SUBTYPES, Prediction, classify,
                                      classify_many, find_component, report_text)

MIN_CONFIDENCE = 0.6          # ниже — не спорим с причиной, выбранной рабочим

AI_FIELDS = ["ai_subtype", "ai_reason", "ai_confidence", "ai_source", "ai_component", "ai_mismatch", "ai_note"]


def reason_label(code: str | None) -> str:
    return reasons_config()["codes"].get(code or "", {}).get("label", code or "—")


def is_mismatch(chosen: str | None, pred: Prediction | None) -> bool:
    """Причина, выбранная рабочим, расходится с тем, что написано в тексте."""
    if pred is None or not chosen or pred.confidence < MIN_CONFIDENCE:
        return False
    if pred.reason == "other":          # микроостановка — «прочее» допустимо почти всегда
        return False
    return chosen != pred.reason


def ai_fields(report: dict, pred: Prediction | None) -> dict[str, Any]:
    if pred is None:
        return dict.fromkeys(AI_FIELDS) | {"ai_mismatch": False}
    return {
        "ai_subtype": pred.subtype, "ai_reason": pred.reason, "ai_confidence": round(pred.confidence, 3),
        "ai_source": pred.source, "ai_component": pred.component or None,
        "ai_mismatch": report.get("status") == "completed" and is_mismatch(report.get("reason"), pred),
        "ai_note": pred.note or None,
    }


def annotate(report: dict) -> dict[str, Any]:
    """AI-поля для одного отчёта (локальная модель)."""
    return ai_fields(report, classify(report_text(report.get("description"), report.get("actions_taken"))))


def annotate_many(reports: list[dict]) -> list[dict[str, Any]]:
    preds = classify_many([report_text(r.get("description"), r.get("actions_taken")) for r in reports])
    return [ai_fields(r, p) for r, p in zip(reports, preds)]


# ─────────────────────────────── LLM ──────────────────────────────────────────

SYSTEM_CLASSIFY = (
    "Ты — помощник мастера на автозаводе (участки: сварка роботами ABB, окраска в камерах с печью сушки, "
    "сборка на конвейерах, контроль качества на стендах). Рабочий описал остановку оборудования. "
    "Определи по тексту, что случилось. Отвечай только JSON-объектом:\n"
    '{"subtype": "<подтип>", "reason": "<код причины>", "component": "<узел или деталь, если названы, иначе \\"\\">", '
    '"confidence": <0..1>, "note": "<одна короткая фраза для мастера: что проверить, без выдуманных цифр>"}\n'
    f"Подтипы: {', '.join(SUBTYPES)}.\n"
    "Коды причин: " + ", ".join(f"{k} ({v['label']})" for k, v in reasons_config()["codes"].items()) + ".\n"
    "Соответствие: датчик/цепь/горелка/калибровка → breakdown; фильтр → consumables; плановое ТО → "
    "planned_maintenance; микроостановка → other. Если текст не про эти случаи — выбери ближайший подтип и "
    "снизь confidence."
)


def _equipment(eq_id: str) -> dict:
    return next((e for e in plant_config()["equipment"] if e["id"] == eq_id), {"name": eq_id, "type": ""})


TYPE_LABEL = {"robot": "сварочный робот", "paint_booth": "камера окраски", "oven": "печь сушки",
              "conveyor": "конвейер", "test_stand": "стенд контроля"}


def llm_classify(client: LLMClient, report: dict) -> Prediction:
    """Разбор текста отчёта языковой моделью. Бросает LLMError, если модель недоступна."""
    eq = _equipment(report["equipment_id"])
    user = (
        f"Оборудование: {eq['name']} ({TYPE_LABEL.get(eq['type'], eq['type'])}).\n"
        f"Сигнал станка: {report.get('machine_reason_text') or 'нет'}.\n"
        f"Причина, выбранная рабочим: {reason_label(report.get('reason'))}.\n"
        f"Описание: «{(report.get('description') or '').strip()}».\n"
        f"Что сделали: «{(report.get('actions_taken') or '').strip()}»."
    )
    res = client.complete_json("classify_report", SYSTEM_CLASSIFY, user, max_tokens=400)
    d = res.data
    sub = str(d.get("subtype", "")).strip()
    if sub not in SUBTYPE_REASON:
        sub = next((s for s in SUBTYPES if s.lower() == sub.lower()), "")
    if not sub:
        raise LLMError(f"модель вернула неизвестный подтип: {d.get('subtype')!r}")
    try:
        conf = float(d.get("confidence", 0.7))
    except (TypeError, ValueError):
        conf = 0.7
    text = report_text(report.get("description"), report.get("actions_taken"))
    comp = str(d.get("component") or "").strip()[:60] or find_component(text)
    note = str(d.get("note") or "").strip()[:200]
    return Prediction(sub, SUBTYPE_REASON[sub], max(0.0, min(conf, 1.0)), "llm", comp, note)


# ─────────────────────────────── сводка ───────────────────────────────────────


def analysis(reports: list[dict], names: dict[str, str]) -> dict[str, Any]:
    """Сводка по отчётам: заполненность, расхождения причин, повторяющиеся проблемы."""
    total = len(reports)
    completed = [r for r in reports if r["status"] == "completed"]
    drafts = total - len(completed)
    mism = [r for r in completed if r.get("ai_mismatch")]
    by_sub: dict[str, dict] = defaultdict(lambda: {"count": 0, "minutes": 0.0})
    rec: dict[tuple[str, str], dict] = defaultdict(lambda: {"count": 0, "minutes": 0.0, "components": Counter()})
    for r in completed:
        sub = r.get("ai_subtype")
        if not sub:
            continue
        by_sub[sub]["count"] += 1
        by_sub[sub]["minutes"] += r.get("duration_min") or 0.0
        if sub in ("плановое ТО", "микроостановка"):
            continue
        k = (r["equipment_id"], sub)
        rec[k]["count"] += 1
        rec[k]["minutes"] += r.get("duration_min") or 0.0
        if r.get("ai_component"):
            rec[k]["components"][r["ai_component"]] += 1
    recurring = sorted(
        ({"equipment_id": e, "name": names.get(e, e), "subtype": s, "subtype_label": SUBTYPE_LABEL.get(s, s),
          "count": v["count"], "minutes": round(v["minutes"]),
          "components": [{"name": c, "count": n} for c, n in v["components"].most_common(3)]}
         for (e, s), v in rec.items() if v["count"] >= 2),
        key=lambda x: (-x["count"], -x["minutes"]))
    wrong_to = Counter(reason_label(r["reason"]) for r in mism)
    return {
        "total": total, "completed": len(completed), "drafts": drafts,
        "draft_share": drafts / total if total else 0.0,
        "mismatches": len(mism), "mismatch_share": len(mism) / len(completed) if completed else 0.0,
        "mismatch_chosen": [{"reason": k, "count": n} for k, n in wrong_to.most_common()],
        "mismatch_examples": [
            {"id": r["id"], "equipment_id": r["equipment_id"], "name": names.get(r["equipment_id"], r["equipment_id"]),
             "ts_start": r["ts_start"], "description": r["description"], "chosen": reason_label(r["reason"]),
             "ai": reason_label(r.get("ai_reason")), "ai_subtype": SUBTYPE_LABEL.get(r.get("ai_subtype") or "", ""),
             "confidence": r.get("ai_confidence")} for r in mism[:6]],
        "by_subtype": sorted(({"subtype": k, "label": SUBTYPE_LABEL.get(k, k), "count": v["count"],
                               "minutes": round(v["minutes"])} for k, v in by_sub.items()),
                             key=lambda x: -x["minutes"]),
        "recurring": recurring[:8],
    }


def accuracy_vs_truth(reports: list[dict]) -> dict[str, Any] | None:
    """Проверка разметки ИИ на скрытой истине симулятора (только для демонстрации качества)."""
    rows = [r for r in reports if r.get("status") == "completed" and r.get("true_subtype") and r.get("ai_subtype")]
    if not rows:
        return None
    ok_sub = sum(r["ai_subtype"] == r["true_subtype"] for r in rows)
    wrong = [r for r in rows if r.get("reason") and r["reason"] != r.get("true_reason")]
    caught = sum(bool(r.get("ai_mismatch")) for r in wrong)
    false_flags = sum(bool(r.get("ai_mismatch")) for r in rows if r.get("reason") == r.get("true_reason"))
    return {"reports": len(rows), "subtype_accuracy": ok_sub / len(rows),
            "wrong_reasons": len(wrong), "wrong_caught": caught, "false_flags": false_flags}
