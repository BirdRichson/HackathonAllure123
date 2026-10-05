"""Сценарии демо: запускаются кнопкой из пульта (клавиша D) и всегда ведут себя одинаково.

Каждый сценарий опирается на реальный эпизод из тестовых данных организаторов:
- sensor_fault — «ABB-01: Ошибка датчика, 25 мин» (01.10);
- chain_break  — «Конвейер-03: Обрыв цепи, 55 мин» (02.10), с предвестником в телеметрии;
- filter_clog  — «Камера-02: Замена фильтра, 40 мин» и брак окраски 3,5–5,2%.
"""

from __future__ import annotations

from typing import Any

SCENARIOS: dict[str, dict[str, Any]] = {
    "sensor_fault": {
        "title": "Авария ABB-01: ошибка датчика",
        "details": "Внезапный отказ без предвестника — участок сварки встаёт, окраска остаётся без кузовов.",
        "equipment_id": "ABB-01",
    },
    "chain_break": {
        "title": "Износ цепи Конвейера-03",
        "details": "Ток привода и вибрация растут ~25 минут работы, затем цепь рвётся. Отчёт заполняет рабочий.",
        "equipment_id": "CONV-03",
    },
    "filter_clog": {
        "title": "Засорение фильтра Камеры-02",
        "details": "Перепад давления растёт, брак окраски (сорность) увеличивается, на пределе — остановка на замену.",
        "equipment_id": "CAM-02",
    },
}


def trigger(sim, name: str) -> dict[str, Any]:
    if name not in SCENARIOS:
        raise KeyError(name)
    sc = SCENARIOS[name]
    eq_id = sc["equipment_id"]
    if name == "sensor_fault":
        sim.schedule_failure(eq_id, "sensor_error", in_op_min=0.5)
    elif name == "chain_break":
        sim.manual_reports.add(eq_id)
        sim.schedule_failure(eq_id, "chain_break", in_op_min=25, lead_min=25)
    elif name == "filter_clog":
        # Короткий «ресурс», чтобы рост перепада был виден за полчаса работы, а не за сутки.
        eq = sim.equipment[eq_id]
        eq.filter_life_h = 1.0
        eq.filter_age_h = 0.5
        sim.manual_reports.add(eq_id)
    return {"name": name, **sc}
