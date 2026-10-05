"""Выводы ИИ: что мешает заводу выполнять цели и что с этим делать.

Как устроено:
1. `build_facts` считает факты за последние 30 дней из данных двойника (простои, брак, телеметрия,
   отчёты рабочих, прогнозы). Это обычный код — цифры проверяемы.
2. `rule_insights` превращает факты в выводы: доказательства, рекомендация и ожидаемый эффект
   в автомобилях за месяц. Работает без сети.
3. `llm_rewrite` (Groq/Gemini) переписывает выводы простым языком, расставляет приоритеты и пишет
   сводку для начальника производства. Числа в его тексте сверяются с расчётом: если модель
   «придумала» число, остаётся текст из шаблона.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from app.assistant.llm import LLMClient, LLMError
from app.assistant.reports import analysis as reports_analysis
from app.config import plant_config, targets_config
from app.sim.engine import DAY_MIN

if TYPE_CHECKING:
    from app.runtime import Runtime

PERIOD_DAYS = 30
WORKDAYS_MONTH = 22
FILTER_SWAP_PA = 300            # замена фильтра по состоянию — с этого перепада растёт сорность
PLANNED_FIX_MIN = 20            # допущение: плановое вмешательство по предупреждению ИИ (осмотр, натяжка, звено)
TARGET_SENSOR_REPAIR_MIN = 15   # допущение: ремонт датчика при запасе у линии и дежурном наладчике


# ─────────────────────────────── форматирование ───────────────────────────────


def n0(x: float) -> str:
    return f"{x:,.0f}".replace(",", " ")


def pct(x: float, d: int = 1) -> str:
    s = f"{x * 100:.{d}f}".replace(".", ",")
    return (s[:-2] if d == 1 and s.endswith(",0") else s) + "%"


def hm(minutes: float) -> str:
    m = int(round(minutes))
    return f"{m // 60} ч {m % 60:02d} мин" if m >= 60 else f"{m} мин"


def plural(n: float, forms: tuple[str, str, str]) -> str:
    """Согласование с числом: 1 сбой, 2 сбоя, 5 сбоев."""
    n = abs(int(round(n)))
    if n % 10 == 1 and n % 100 != 11:
        return forms[0]
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return forms[1]
    return forms[2]


def num(x: float) -> str:
    return f"{x:g}".replace(".", ",")


def period_end(sim) -> float:
    """Конец последней закрытой смены: выводы меняются раз в смену и не «прыгают» каждую секунду."""
    from app.views import shift_window

    sw = shift_window(sim)
    return sw["start"] if sw["in_shift"] else sw["end"]


# ─────────────────────────────── факты ────────────────────────────────────────


def build_facts(rt: "Runtime", forecast: dict | None) -> dict[str, Any]:
    from app.views import _in_shift_minutes, reconciliation, stop_intervals

    w = rt.world
    sim = w.sim
    plant = plant_config()
    takt = float(plant["rates"]["takt_min"])
    t1 = period_end(sim)
    t0 = max(0.0, t1 - PERIOD_DAYS * DAY_MIN)
    windows = sim.cal.shift_windows(t0, t1)
    workdays = max(len(windows) / 2, 1.0)
    k = WORKDAYS_MONTH / workdays
    names = {e["id"]: e["name"] for e in plant["equipment"]}
    area_names = {a["id"]: a["name"] for a in plant["areas"]}

    stops = stop_intervals(sim, t0, t1)
    for s in stops:
        s["min"] = _in_shift_minutes(sim, s["start"], s["end"])
    eq_stops = [s for s in stops if s["kind"] in ("equipment", "planned") and s["min"] > 0]

    def group(text: str) -> dict:
        sel = [s for s in eq_stops if s["reason_text"] == text]
        by_eq: dict[str, list] = {}
        for s in sel:
            by_eq.setdefault(s["equipment_id"], []).append(s["min"])
        return {"count": len(sel), "minutes": sum(s["min"] for s in sel),
                "avg": sum(s["end"] - s["start"] for s in sel) / len(sel) if sel else 0.0,
                "by_equipment": sorted(({"id": e, "name": names.get(e, e), "count": len(v), "minutes": sum(v)}
                                        for e, v in by_eq.items()), key=lambda x: -x["minutes"])}

    # окраска и фильтры
    q = w.paint_quality.stats(t0, t1, FILTER_SWAP_PA)
    f = plant["equipment_types"]["paint_booth"]["filter"]
    frac = ((FILTER_SWAP_PA - f["dp_new_pa"]) / (f["dp_limit_pa"] - f["dp_new_pa"])) ** (1 / 1.6)

    # отказы по типам
    filters = group(plant["equipment_types"]["paint_booth"]["filter"]["reason_text"])
    chain = group("Обрыв цепи")
    burner = group("Сбой горелки печи")
    sensor = group("Ошибка датчика")
    planned = [s for s in eq_stops if s["planned"]]
    planned_by_area: dict[str, float] = {}
    for s in planned:
        planned_by_area[s["area_id"]] = planned_by_area.get(s["area_id"], 0.0) + s["min"]

    # прогнозы отказов за период
    mon = w.monitor
    outcomes = [o for o in mon.outcomes if t0 <= o["t"] < t1] if mon else []
    hits = [o for o in outcomes if o["alerted"]]

    # отчёты рабочих
    t0_iso, t1_iso = w.iso(t0), w.iso(t1)
    reps = [r for r in rt.db.list_reports(limit=5000) if t0_iso <= (r["ts_start"] or "") < t1_iso]
    rep = reports_analysis(reps, names)

    # учёт простоев: потеря времени против записанного
    rec = reconciliation(rt, days=PERIOD_DAYS)
    rec = [r for r in rec if r["date"] >= sim.cal.dt(t0).date().isoformat()]
    unreg = sum(max(0.0, r["unregistered_min"]) for r in rec)
    micro = [s for s in stops if s["kind"] == "micro"]

    # где теряем больше всего (без ожидания соседних участков)
    loss_by_area: dict[str, float] = {}
    for s in stops:
        if s["kind"] != "flow":
            loss_by_area[s["area_id"]] = loss_by_area.get(s["area_id"], 0.0) + s["min"]

    return {
        "period": {"from": t0_iso, "to": t1_iso, "workdays": workdays, "month_factor": k},
        "takt_min": takt,
        "paint": {**q, "filter_stops": filters, "swap_pa": FILTER_SWAP_PA, "limit_pa": f["dp_limit_pa"],
                  "filter_use_ratio": frac},
        "chain": chain, "burner": burner, "sensor": sensor,
        "planned": {"count": len(planned), "minutes": sum(s["min"] for s in planned),
                    "by_area": {area_names.get(a, a): m for a, m in planned_by_area.items()},
                    "window": sim.window},
        "predictions": {"failures": len(outcomes), "predicted": len(hits),
                        "mean_lead": (sum(o["lead_min"] for o in hits) / len(hits)) if hits else None},
        "reports": rep,
        "accounting": {"unregistered_min": unreg, "shifts": len(rec) / 3 if rec else 0,
                       "micro_count": len(micro), "micro_min": sum(s["min"] for s in micro)},
        "loss_by_area": {area_names.get(a, a): m for a, m in sorted(loss_by_area.items(), key=lambda x: -x[1])},
        "forecast": forecast,
        "names": names,
    }


# ─────────────────────────────── выводы по правилам ───────────────────────────


def _severity(cars: float) -> str:
    return "critical" if cars >= 25 else "warning" if cars >= 8 else "info"


def rule_insights(facts: dict) -> list[dict]:
    k = facts["period"]["month_factor"]
    takt = facts["takt_min"]
    out: list[dict] = []

    # 1. Фильтры окраски и брак
    p = facts["paint"]
    if p["units"] >= 200 and p["units_hi"] >= 50 and p["rate_hi"] > p["rate_lo"] * 1.3:
        fmin = p["filter_stops"]["minutes"] * k
        cars = fmin / takt
        defects = p["excess_defects"] * k
        rate_all = p["defects"] / p["units"]
        rate_new = (p["defects"] - p["excess_defects"]) / p["units"]
        extra_filters = 1 / p["filter_use_ratio"] - 1
        out.append({
            "id": "paint_filters", "kind": "quality", "area_id": "PAINT", "equipment_ids": ["CAM-01", "CAM-02"],
            "title": "Брак окраски растёт вместе с засорением фильтров камер",
            "summary": (f"При перепаде на фильтрах {p['swap_pa']} Па и выше брак окраски {pct(p['rate_hi'])}, "
                        f"при чистых фильтрах — {pct(p['rate_lo'])}. Фильтры меняют только на пределе "
                        f"{p['limit_pa']} Па, с остановкой камеры посреди смены."),
            "evidence": [
                f"{n0(p['units_hi'])} из {n0(p['units'])} кузовов за 30 дней окрашены при перепаде ≥{p['swap_pa']} Па",
                f"Брак окраски: {pct(p['rate_hi'])} против {pct(p['rate_lo'])}, лишних дефектов ≈{n0(p['excess_defects'])}",
                f"Вынужденных замен фильтра в смену: {p['filter_stops']['count']}, простой {hm(p['filter_stops']['minutes'])}",
            ],
            "recommendation": (f"Менять фильтры по состоянию: как только перепад превысил {p['swap_pa']} Па — "
                               "в ближайшую ночь, в нерабочее окно 00:00–08:00."),
            "effect": {"cars_month": round(cars), "defects_month": round(defects), "minutes_month": round(fmin),
                       "text": f"≈ −{n0(defects)} дефектов окраски в месяц (брак {pct(rate_all)} → ≈{pct(rate_new)}) "
                               f"и до +{n0(cars)} авто за счёт замен вне смены"},
            "cost": f"фильтры будут меняться чаще — расход ≈ +{pct(extra_filters, 0)}",
            "assumptions": ["ресурс фильтра и порог сорности — допущения модели (A7)"],
            "confidence": "высокая", "severity": "critical" if defects >= 50 else _severity(cars),
        })

    # 2. Плановое ТО в смену
    pl = facts["planned"]
    if pl["window"] == "in_shift" and pl["count"] > 0:
        mins = pl["minutes"] * k
        cars = mins / takt
        areas = ", ".join(f"{a.lower()} — {hm(m)}" for a, m in sorted(pl["by_area"].items(), key=lambda x: -x[1]))
        out.append({
            "id": "maintenance_night", "kind": "maintenance", "area_id": None, "equipment_ids": [],
            "title": "Плановое ТО останавливает участки в начале смены",
            "summary": (f"За 30 дней {pl['count']} {plural(pl['count'], ('плановое ТО заняло', 'плановых ТО заняли', 'плановых ТО заняли'))} "
                        f"{hm(pl['minutes'])} рабочего времени. "
                        "Ночью завод не работает: то же ТО можно делать без потери выпуска."),
            "evidence": [f"ТО по участкам: {areas}",
                         "Смены 08:00–16:00 и 16:00–24:00, окно 00:00–08:00 свободно"],
            "recommendation": "Перенести плановое ТО в ночное окно 00:00–08:00 (дежурная бригада ТО).",
            "effect": {"cars_month": round(cars), "minutes_month": round(mins),
                       "text": f"до +{n0(cars)} авто в месяц, {hm(mins)} рабочего времени возвращается в смены"},
            "cost": "ночная бригада ТО или сдвиг графика ремонтников",
            "assumptions": ["эффект — верхняя оценка: часть остановок гасят буферы между участками"],
            "confidence": "высокая", "severity": _severity(cars),
        })

    # 3. Износовые отказы с предвестником: цепь конвейера и горелка печи
    ch, bu, pr = facts["chain"], facts["burner"], facts["predictions"]
    if ch["count"] + bu["count"] > 0:
        cnt = ch["count"] + bu["count"]
        mins_total = ch["minutes"] + bu["minutes"]
        avg = (ch["avg"] * ch["count"] + bu["avg"] * bu["count"]) / cnt
        saved = max(0.0, avg - PLANNED_FIX_MIN) * cnt * k
        cars = saved / takt
        top = (ch["by_equipment"] or bu["by_equipment"])[0]
        ev = [f"Обрывов цепи: {ch['count']} ({hm(ch['minutes'])}), сбоев горелки печи: {bu['count']} ({hm(bu['minutes'])})",
              f"Средний аварийный ремонт — {hm(avg)}; чаще всего — {top['name']}"]
        if pr["failures"]:
            lead = f", в среднем за {n0(pr['mean_lead'])} мин" if pr["mean_lead"] else ""
            ev.append(f"Модель прогноза предупредила {pr['predicted']} из {pr['failures']} таких отказов{lead}")
        out.append({
            "id": "wear_failures", "kind": "prediction", "area_id": "ASSY" if ch["count"] >= bu["count"] else "PAINT",
            "equipment_ids": [x["id"] for x in ch["by_equipment"] + bu["by_equipment"]],
            "title": "Обрывы цепи конвейеров можно предупреждать заранее",
            "summary": (f"За 30 дней {cnt} {plural(cnt, ('аварийная остановка', 'аварийные остановки', 'аварийных остановок'))} "
                        f"по износу — {hm(mins_total)} простоя. "
                        "За 1–3 часа до обрыва растут ток привода и вибрация — это видно в телеметрии."),
            "evidence": ev,
            "recommendation": ("Реагировать на прогноз ИИ: при предупреждении — плановый осмотр и натяжка цепи "
                               "в ближайшую паузу или ночью, вместо аварийного ремонта посреди смены."),
            "effect": {"cars_month": round(cars), "minutes_month": round(saved),
                       "text": f"до +{n0(cars)} авто в месяц: плановое вмешательство ≈{PLANNED_FIX_MIN} мин "
                               f"вместо аварии ≈{n0(avg)} мин"},
            "cost": "регламент реакции на предупреждение; датчики тока и вибрации на приводах",
            "assumptions": [f"плановое вмешательство — {PLANNED_FIX_MIN} мин (допущение)"],
            "confidence": "средняя", "severity": _severity(cars),
        })

    # 4. Сбои датчиков роботов — случайные, сокращаем время реакции
    se = facts["sensor"]
    if se["count"] > 0:
        saved = max(0.0, se["avg"] - TARGET_SENSOR_REPAIR_MIN) * se["count"] * k
        cars = saved / takt
        top = se["by_equipment"][0]
        comps = [c for r in facts["reports"]["recurring"] if r["subtype"] == "датчик" for c in r["components"]]
        comp_txt = ""
        if comps:
            best = max(comps, key=lambda c: c["count"])
            comp_txt = f"; в отчётах чаще всего упоминается «{best['name']}»"
        out.append({
            "id": "robot_sensors", "kind": "reliability", "area_id": "WELD",
            "equipment_ids": [x["id"] for x in se["by_equipment"]],
            "title": "Сбои датчиков роботов: прогноз не поможет, поможет скорость реакции",
            "summary": (f"{se['count']} {plural(se['count'], ('сбой', 'сбоя', 'сбоев'))} датчиков за 30 дней, "
                        f"{hm(se['minutes'])} простоя сварки. "
                        "Сбои случайные: предвестника в телеметрии нет, модель это подтверждает."),
            "evidence": [f"Больше всего — {top['name']}: {top['count']} {plural(top['count'], ('сбой', 'сбоя', 'сбоев'))}, "
                         f"{hm(top['minutes'])}{comp_txt}",
                         f"Средний ремонт — {hm(se['avg'])}"],
            "recommendation": ("Держать запас датчиков и разъёмов у линии сварки, проверять разъёмы на каждом ТО, "
                               "закрепить дежурного наладчика за участком."),
            "effect": {"cars_month": round(cars), "minutes_month": round(saved),
                       "text": f"до +{n0(cars)} авто в месяц при ремонте ≈{TARGET_SENSOR_REPAIR_MIN} мин "
                               f"вместо {n0(se['avg'])}"},
            "cost": "запас датчиков (ЗИП) у линии",
            "assumptions": [f"ремонт за {TARGET_SENSOR_REPAIR_MIN} мин при запасе у линии (допущение)"],
            "confidence": "средняя", "severity": _severity(cars),
        })

    # 5. Качество учёта простоев
    r, acc = facts["reports"], facts["accounting"]
    if r["total"]:
        per_shift = acc["unregistered_min"] / acc["shifts"] if acc["shifts"] else 0.0
        ev = [f"Не заполнено {r['drafts']} из {r['total']} {plural(r['total'], ('отчёта', 'отчётов', 'отчётов'))} "
              f"({pct(r['draft_share'], 0)})",
              f"Причина выбрана неверно (по тексту отчёта): {r['mismatches']} "
              f"{plural(r['mismatches'], ('отчёт', 'отчёта', 'отчётов'))}, {pct(r['mismatch_share'], 0)}"]
        if r["mismatch_chosen"]:
            ev.append("Вместо настоящей причины чаще ставят «" + r["mismatch_chosen"][0]["reason"] + "»")
        ev.append(f"Незаписанные потери: ≈{n0(per_shift)} мин за смену на участок; микроостановок за 30 дней — "
                  f"{acc['micro_count']} ({hm(acc['micro_min'])})")
        out.append({
            "id": "reports_quality", "kind": "data", "area_id": None, "equipment_ids": [],
            "title": "Учёт простоев неполный: часть потерь не видна в отчётах",
            "summary": (f"ИИ сверил текст отчётов с выбранной причиной: в {pct(r['mismatch_share'], 0)} случаев "
                        "причина указана неверно, и в статистике поломки уходят в «прочее»."),
            "evidence": ev,
            "recommendation": ("Форма на планшете с подсказкой причины от ИИ; короткие остановки фиксировать "
                               "по сигналу станка автоматически."),
            "effect": {"cars_month": 0, "text": "точная статистика причин — основа для всех остальных мер"},
            "cost": "планшет у линии или Telegram-бот",
            "assumptions": [],
            "confidence": "высокая",
            "severity": "warning" if r["mismatch_share"] > 0.1 or r["draft_share"] > 0.1 else "info",
        })

    # 6. Месячный план
    fc = facts.get("forecast")
    if fc:
        measures = sum(i["effect"].get("cars_month", 0) for i in out)
        left_share = fc["shifts_left"] / max(fc["shifts_total"], 1)
        with_measures = fc["p50"] + measures * left_share
        target = fc["target"]
        ev = [f"Прогноз на конец месяца (на начало смены): {n0(fc['p50'])} авто (80% интервал {n0(fc['p10'])}–{n0(fc['p90'])}), "
              f"вероятность выполнить цель — {pct(fc['prob_target'], 0)}",
              f"Средняя смена — {n0(fc['shift_mean'])} авто; для цели нужно {n0(fc['required_per_shift'] or 0)} за смену",
              f"Предел двух смен при идеальном цикле {num(plant_config()['rates']['ideal_cycle_min'])} мин — "
              f"≈{n0(fc['max_theoretical'])} авто в месяц"]
        out.append({
            "id": "month_plan", "kind": "plan", "area_id": None, "equipment_ids": [],
            "title": f"Цель {n0(target)} авто в месяц при нынешних потерях не выполняется",
            "summary": (f"Ожидаемый выпуск — {n0(fc['p50'])} авто, не хватает ≈{n0(max(0, target - fc['p50']))}. "
                        f"Цель близка к пределу двух смен, поэтому важна каждая минута простоя."),
            "evidence": ev,
            "recommendation": (f"Меры из выводов выше дают до +{n0(measures)} авто в месяц. Оставшийся разрыв — "
                               "субботние смены по необходимости."),
            "effect": {"cars_month": 0, "text": f"с мерами в этом месяце — ≈{n0(with_measures)} авто; в полном "
                                                f"месяце до +{n0(measures)} авто"},
            "cost": "",
            "assumptions": ["план по моделям в данных — 4800, цель — 5500 (D6)"],
            "confidence": "средняя",
            "severity": "critical" if fc["prob_target"] < 0.5 else "info",
        })

    for i in out:
        i["source"] = "rules"
    sev_rank = {"critical": 0, "warning": 1, "info": 2}
    out.sort(key=lambda i: (sev_rank[i["severity"]], -i["effect"].get("cars_month", 0)))
    for n, i in enumerate(out, 1):
        i["rank"] = n
    return out


def template_summary(insights: list[dict], facts: dict) -> str:
    gains = [i for i in insights if i["effect"].get("cars_month")]
    total = sum(i["effect"]["cars_month"] for i in gains)
    worst = next(iter(facts["loss_by_area"].items()), None)
    parts = []
    if worst:
        parts.append(f"За 30 дней больше всего рабочего времени теряет участок «{worst[0]}» — {hm(worst[1])} остановок.")
    top = [i["title"].split(":")[0] for i in gains[:2]]
    top = [t[0].lower() + t[1:] for t in top]
    if top:
        parts.append("Главные резервы: " + "; ".join(top) + ".")
    if total:
        parts.append(f"Вместе меры дают до +{n0(total)} авто в месяц.")
    fc = facts.get("forecast")
    if fc:
        parts.append(f"Прогноз месяца — {n0(fc['p50'])} авто при цели {n0(fc['target'])}.")
    return " ".join(parts)


# ─────────────────────────────── LLM ──────────────────────────────────────────

SYSTEM_INSIGHTS = (
    "Ты — ИИ-помощник начальника производства автозавода (сварка, окраска, сборка; 2 смены 08:00–16:00 и "
    "16:00–24:00 в будни, ночью 00:00–08:00 завод не работает). Тебе дают выводы, посчитанные по данным "
    "цифрового двойника. Перепиши их коротко и по-деловому для мастеров и начальника цеха, расставь по приоритету "
    "и напиши общую сводку.\n"
    "Правила:\n"
    "- Используй ТОЛЬКО числа из входных данных, не меняй и не округляй их по-своему, не придумывай новых.\n"
    "- Время работ предлагай «ночью, в нерабочее окно», а не «в пересменку» — смены идут без перерыва.\n"
    "- Без канцелярита и англицизмов, без markdown. Заголовок — до 10 слов, summary и recommendation — "
    "по 1–2 предложения.\n"
    "Ответ — только JSON:\n"
    '{"summary": "<3–4 предложения: что главное за период и что делать в первую очередь>", '
    '"items": [{"id": "<id вывода>", "title": "...", "summary": "...", "recommendation": "..."}], '
    '"order": ["<id в порядке приоритета>"]}'
)

NUM_RE = re.compile(r"\d[\d\s  ]*(?:[.,]\d+)?")


def _numbers(text: str) -> list[float]:
    out = []
    for m in NUM_RE.finditer(text):
        s = re.sub(r"[\s  ]", "", m.group()).replace(",", ".")
        try:
            out.append(float(s))
        except ValueError:
            pass
    return out


def numbers_ok(text: str, allowed: set[float]) -> bool:
    """Все заметные числа в тексте модели есть во входных данных (с допуском на округление)."""
    for x in _numbers(text):
        if x <= 12:                       # мелкие числа (часы, «2 смены») не проверяем
            continue
        if not any(abs(x - a) <= max(0.6, 0.01 * a) for a in allowed):
            return False
    return True


def llm_payload(insights: list[dict], facts: dict, kpi: dict | None) -> dict:
    per = facts["period"]
    payload = {
        "период": f"{per['from'][:10]} — {per['to'][:10]}, рабочих дней: {per['workdays']:.0f}",
        "выводы": [{"id": i["id"], "важность": i["severity"], "заголовок": i["title"], "суть": i["summary"],
                    "доказательства": i["evidence"], "рекомендация": i["recommendation"],
                    "эффект": i["effect"]["text"], "затраты": i.get("cost") or "",
                    "допущения": i.get("assumptions") or []} for i in insights],
        "потери_по_участкам_мин": {a: round(m) for a, m in facts["loss_by_area"].items()},
    }
    if kpi:
        payload["текущая_смена"] = kpi
    return payload


def llm_rewrite(client: LLMClient, insights: list[dict], facts: dict, kpi: dict | None,
                use_cache: bool = True) -> tuple[str | None, list[dict], dict]:
    """Текст выводов от LLM поверх расчёта. Возвращает (сводка, выводы, сведения о вызове)."""
    payload = llm_payload(insights, facts, kpi)
    user = json.dumps(payload, ensure_ascii=False)
    allowed = set(_numbers(user))
    res = client.complete_json("insights", SYSTEM_INSIGHTS, user, max_tokens=2500, use_cache=use_cache)
    data = res.data
    rejected = 0
    by_id = {i["id"]: i for i in insights}
    items = {it.get("id"): it for it in data.get("items", []) if isinstance(it, dict)}
    out = []
    for i in insights:
        new = {"source": "rules", **i}
        it = items.get(i["id"])
        if it:
            fields = {f: str(it.get(f) or "").strip() for f in ("title", "summary", "recommendation")}
            if all(fields.values()) and all(numbers_ok(v, allowed) for v in fields.values()):
                new.update(fields, source="llm")
            else:
                rejected += 1
        out.append(new)
    order = [x for x in data.get("order", []) if x in by_id]
    if order:
        rank = {x: n for n, x in enumerate(order)}
        out.sort(key=lambda i: rank.get(i["id"], len(rank) + i["rank"]))
        for n, i in enumerate(out, 1):
            i["rank"] = n
    summary = str(data.get("summary") or "").strip() or None
    if summary and not numbers_ok(summary, allowed):
        summary, rejected = None, rejected + 1
    meta = {"provider": res.provider, "model": res.model, "label": res.label, "cached": res.cached,
            "latency_ms": res.latency_ms, "rejected_by_guard": rejected}
    return summary, out, meta


__all__ = ["build_facts", "rule_insights", "template_summary", "llm_rewrite", "period_end", "LLMError"]
