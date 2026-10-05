"""Импорт данных организаторов (docx, xlsx, csv) и первичный анализ.

Вход — файл в формате тестовых данных: 4 таблицы (работа линий, простои, план по моделям,
качество), схема участков и «дополнительные вводные» с целевыми показателями.
Выход — нормализованные таблицы, KPI по строкам, сверка простоев и список находок,
которые двойник показывает в разделе «Данные завода».
"""

from __future__ import annotations

import io
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from app.config import TZ_NAME, plant_config, reasons_config, targets_config
from app.kpi.engine import oee

# Заголовки таблиц в данных организаторов → нормализованные колонки.
HEADERS = {
    "lines": {"Дата": "date", "Линия": "line_id", "План": "plan_units", "Факт": "fact_units",
              "Время работы, ч": "run_hours", "Загрузка, %": "load_pct"},
    "downtime": {"Дата": "date", "Участок": "area", "Оборудование": "equipment", "Причина": "reason_text",
                 "Длительность, мин": "duration_min"},
    "plan_models": {"Модель": "model", "План на месяц": "plan_month_units"},
    "quality": {"Дата": "date", "Участок": "area", "Выпущено": "produced", "Брак": "defects", "% брака": "defect_pct"},
}
NORMAL_COLUMNS = {
    "lines": ["date", "line_id", "plan_units", "fact_units", "run_hours", "load_pct"],
    "downtime": ["date", "area", "equipment", "reason_text", "duration_min"],
    "plan_models": ["model", "plan_month_units"],
    "quality": ["date", "area", "produced", "defects", "defect_pct"],
}
NUMERIC = {"plan_units", "fact_units", "run_hours", "load_pct", "duration_min", "plan_month_units",
           "produced", "defects", "defect_pct"}


# ─────────────────────────────── разбор значений ───────────────────────────────


def _num(v: Any) -> float:
    """Число с запятой или точкой: «1,7» и «7.8»."""
    s = str(v).strip().replace("\xa0", "").replace(" ", "").replace("%", "").replace(",", ".")
    return float(s)


def _date(v: Any) -> str:
    s = str(v).strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d.%m.%y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"не удалось разобрать дату «{s}»")


def _norm_header(h: str) -> str:
    return re.sub(r"\s+", " ", h.replace("\\", "")).strip()


def _detect(columns: list[str]) -> str | None:
    cols = {_norm_header(c) for c in columns}
    for kind, mapping in HEADERS.items():
        if set(mapping) <= cols or set(NORMAL_COLUMNS[kind]) <= cols:
            return kind
    return None


def _normalize(kind: str, df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns={c: _norm_header(c) for c in df.columns}).rename(columns=HEADERS[kind])
    df = df[NORMAL_COLUMNS[kind]].copy()
    for c in df.columns:
        if c == "date":
            df[c] = df[c].map(_date)
        elif c in NUMERIC:
            df[c] = df[c].map(_num)
        else:
            df[c] = df[c].astype(str).str.strip()
    for c in ("plan_units", "fact_units", "plan_month_units", "produced", "defects"):
        if c in df.columns:
            df[c] = df[c].round().astype(int)
    return df.reset_index(drop=True)


# ─────────────────────────────── чтение файлов ────────────────────────────────


def _docx_tables_and_text(data: bytes) -> tuple[list[pd.DataFrame], list[str]]:
    import docx  # python-docx

    doc = docx.Document(io.BytesIO(data))
    tables = []
    for t in doc.tables:
        rows = [[c.text.strip() for c in r.cells] for r in t.rows]
        if len(rows) >= 2:
            tables.append(pd.DataFrame(rows[1:], columns=rows[0]))
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    return tables, paragraphs


def parse_targets(paragraphs: list[str]) -> dict[str, Any]:
    """Цели из «Дополнительных вводных»: смены, OEE, брак, лимит простоя, месячный план."""
    text = " ".join(paragraphs)
    found: dict[str, Any] = {}
    if m := re.search(r"(\d+)\s*смен\w*\s*по\s*(\d+)\s*час", text):
        found["shifts_per_day"], found["shift_hours"] = int(m.group(1)), int(m.group(2))
    if m := re.search(r"OEE[^\d]*(\d+(?:[.,]\d+)?)\s*%", text):
        found["oee_min"] = _num(m.group(1)) / 100
    if m := re.search(r"брак\w*[^\d]*(\d+(?:[.,]\d+)?)\s*%", text, re.IGNORECASE):
        found["defect_rate_max"] = _num(m.group(1)) / 100
    if m := re.search(r"простой[^\d]*(\d+)\s*минут", text, re.IGNORECASE):
        found["critical_downtime_max_min_per_day"] = int(m.group(1))
    if m := re.search(r"(\d[\d\s\xa0]*\d)\s*автомобил\w*\s*в\s*месяц", text):
        found["monthly_output_min"] = int(re.sub(r"\D", "", m.group(1)))
    return found


def parse_scheme(paragraphs: list[str]) -> list[str]:
    for p in paragraphs:
        if "→" in p:
            return [s.strip() for s in p.split("→") if s.strip()]
    return []


def read_files(files: list[tuple[str, bytes]]) -> dict[str, Any]:
    """Прочитать один docx или набор csv/xlsx. Возвращает таблицы, цели, схему и предупреждения."""
    tables: dict[str, pd.DataFrame] = {}
    paragraphs: list[str] = []
    warnings: list[str] = []
    for name, data in files:
        ext = Path(name).suffix.lower()
        if ext == ".docx":
            raw, paras = _docx_tables_and_text(data)
            paragraphs += paras
        elif ext in (".xlsx", ".xls"):
            raw = list(pd.read_excel(io.BytesIO(data), sheet_name=None, dtype=str).values())
        elif ext == ".csv":
            raw = [pd.read_csv(io.BytesIO(data), dtype=str)]
        else:
            warnings.append(f"{name}: формат не поддерживается (нужен docx, xlsx или csv)")
            continue
        for df in raw:
            kind = _detect(list(df.columns))
            if kind is None:
                warnings.append(f"{name}: таблица с колонками {list(df.columns)} не распознана")
                continue
            tables[kind] = _normalize(kind, df)
    return {"tables": tables, "targets": parse_targets(paragraphs), "scheme": parse_scheme(paragraphs),
            "warnings": warnings}


# ─────────────────────────────── анализ ───────────────────────────────────────


def _pct(x: float, digits: int = 1) -> str:
    return f"{x * 100:.{digits}f}".replace(".", ",") + "%"


def _fmt_date(iso: str) -> str:
    d = datetime.fromisoformat(iso)
    return d.strftime("%d.%m")


def analyze(parsed: dict[str, Any]) -> dict[str, Any]:
    plant = plant_config()
    tg = {**targets_config(), **parsed["targets"]}
    tables = parsed["tables"]
    warnings = list(parsed["warnings"])
    findings: list[dict[str, Any]] = []
    shift_min = 60 * float(tg.get("shift_hours", plant["schedule"]["shift_hours"]))
    cycle = float(plant["rates"]["ideal_cycle_min"])

    # Сопоставление названий из данных с моделью завода.
    line_area = {a["line_id"]: a for a in plant["areas"] if a.get("line_id")}
    name_area = {a["name"]: a["id"] for a in plant["areas"]}
    eq_by_name = {e["name"]: e for e in plant["equipment"]}
    reason_map = reasons_config()["mapping"]

    lines = tables.get("lines", pd.DataFrame(columns=NORMAL_COLUMNS["lines"]))
    quality = tables.get("quality", pd.DataFrame(columns=NORMAL_COLUMNS["quality"]))
    downtime = tables.get("downtime", pd.DataFrame(columns=NORMAL_COLUMNS["downtime"]))
    plan_models = tables.get("plan_models", pd.DataFrame(columns=NORMAL_COLUMNS["plan_models"]))

    # Простои: оборудование и причины → коды двойника.
    dt_rows = []
    for r in downtime.to_dict("records"):
        eq = eq_by_name.get(r["equipment"])
        mapped = reason_map.get(r["reason_text"])
        if eq is None:
            warnings.append(f"Оборудование «{r['equipment']}» нет в модели завода")
        if mapped is None:
            warnings.append(f"Причина «{r['reason_text']}» не в справочнике — записана как «прочее»")
        code = mapped["code"] if mapped else "other"
        dt_rows.append({**r, "equipment_id": eq["id"] if eq else None,
                        "area_id": name_area.get(r["area"]), "reason": code,
                        "planned": bool(reasons_config()["codes"][code]["planned"])})

    # KPI по каждой строке «линия × дата» (одна строка = одна смена, решение D1).
    kpi_rows, recon = [], []
    for r in lines.to_dict("records"):
        area = line_area.get(r["line_id"]) or {"id": name_area.get(r["line_id"].split("-")[0]),
                                                 "name": r["line_id"].split("-")[0]}
        q = quality[(quality["date"] == r["date"]) & (quality["area"] == area["name"])]
        defects = int(q["defects"].iloc[0]) if len(q) else 0
        run_min = r["run_hours"] * 60
        k = oee(run_min, shift_min, r["fact_units"], defects, cycle)
        k_plan = oee(run_min, shift_min, r["fact_units"], defects, shift_min / r["plan_units"])
        load_calc = r["run_hours"] / (shift_min / 60) * 100
        kpi_rows.append({
            "date": r["date"], "line_id": r["line_id"], "area_id": area["id"], "area": area["name"],
            "plan_units": r["plan_units"], "fact_units": r["fact_units"], "defects": defects,
            "good_units": r["fact_units"] - defects, "run_hours": r["run_hours"], "load_pct": r["load_pct"],
            "load_pct_calc": round(load_calc, 1),
            **{k2: round(v, 4) for k2, v in k.items()},
            "oee_plan_takt": round(k_plan["oee"], 4), "performance_plan_takt": round(k_plan["performance"], 4),
            "defect_rate": round(defects / r["fact_units"], 4) if r["fact_units"] else 0.0,
        })
        if abs(load_calc - r["load_pct"]) >= 0.75:
            warnings.append(f"{_fmt_date(r['date'])} {r['line_id']}: загрузка {r['load_pct']:.0f}%, а по времени "
                            f"работы {load_calc:.1f}% — расхождение в исходных данных")
        lost = shift_min - run_min
        reg = sum(d["duration_min"] for d in dt_rows if d["date"] == r["date"] and d["area"] == area["name"])
        recon.append({"date": r["date"], "line_id": r["line_id"], "area": area["name"],
                      "lost_min": round(lost, 1), "registered_min": round(reg, 1),
                      "gap_min": round(lost - reg, 1)})

    # ── находки ──
    dmax = float(tg["defect_rate_max"])
    bad_q = [k for k in kpi_rows if k["defect_rate"] > dmax]
    for area in sorted({k["area"] for k in bad_q}):
        rows = [k for k in bad_q if k["area"] == area]
        vals = ", ".join(f"{_pct(k['defect_rate'])} ({_fmt_date(k['date'])})" for k in rows)
        findings.append({
            "severity": "critical" if len(rows) > 1 else "warning", "kind": "quality",
            "title": f"{area}: брак выше нормы {_pct(dmax, 0)}",
            "details": f"Брак {vals}." + (" Растёт от дня ко дню." if len(rows) > 1 and
                                           rows[-1]["defect_rate"] > rows[0]["defect_rate"] else ""),
            "area": area,
        })

    omin = float(tg["oee_min"])
    for k in kpi_rows:
        if k["oee"] < omin:
            findings.append({"severity": "warning", "kind": "oee",
                             "title": f"{k['area']} {_fmt_date(k['date'])}: OEE {_pct(k['oee'])} ниже цели {_pct(omin, 0)}",
                             "details": f"Доступность {_pct(k['availability'])}, качество {_pct(k['quality'])}.",
                             "area": k["area"]})
        elif k["oee"] < omin + 0.01:
            findings.append({"severity": "info", "kind": "oee",
                             "title": f"{k['area']} {_fmt_date(k['date'])}: OEE {_pct(k['oee'])} — на границе цели {_pct(omin, 0)}",
                             "details": f"Время работы {k['run_hours']:.1f} ч из 8, брак {_pct(k['defect_rate'])}.".replace(".", ",", 1),
                             "area": k["area"]})

    lim = float(tg["critical_downtime_max_min_per_day"])
    warn = float(tg.get("critical_downtime_warn_min", 0.75 * lim))
    per_eq: dict[tuple[str, str], float] = {}
    for d in dt_rows:
        if not d["planned"]:
            per_eq[(d["date"], d["equipment"])] = per_eq.get((d["date"], d["equipment"]), 0) + d["duration_min"]
    for (date, eq), mins in sorted(per_eq.items()):
        if mins >= warn:
            findings.append({"severity": "critical" if mins > lim else "warning", "kind": "downtime_limit",
                             "title": f"{eq}: простой {mins:.0f} мин за {_fmt_date(date)} — {mins / lim * 100:.0f}% лимита {lim:.0f} мин",
                             "details": "Лимит простоя критического оборудования — 60 минут в сутки.",
                             "equipment": eq})

    # Сверка учёта: потеря рабочего времени против записанных простоев (решение D9).
    gaps = sorted((rc for rc in recon if abs(rc["gap_min"]) >= 10), key=lambda rc: -abs(rc["gap_min"]))
    if gaps:
        parts = []
        for rc in gaps[:3]:
            if rc["gap_min"] > 0:
                parts.append(f"{rc['area']} {_fmt_date(rc['date'])}: потеряно {rc['lost_min']:.0f} мин, "
                             f"записано {rc['registered_min']:.0f} — {rc['gap_min']:.0f} мин не объяснены")
            else:
                parts.append(f"{rc['area']} {_fmt_date(rc['date'])}: записано {rc['registered_min']:.0f} мин "
                             f"простоя, а потеря времени работы — {rc['lost_min']:.0f} мин")
        findings.append({"severity": "info", "kind": "reconciliation",
                         "title": f"Учёт простоев не сходится в {len(gaps)} из {len(recon)} строк",
                         "details": "; ".join(parts) + ". Простои записаны за сутки, а время работы — за смену; "
                                    "часть коротких остановок не записывается.",
                         "items": gaps})

    by_day: dict[str, list[dict]] = {}
    for k in kpi_rows:
        by_day.setdefault(k["date"], []).append(k)
    bottlenecks = []
    for date, rows in sorted(by_day.items()):
        b = min(rows, key=lambda k: k["good_units"])
        bottlenecks.append({"date": date, "area": b["area"], "good_units": b["good_units"]})
    if len({b["area"] for b in bottlenecks}) > 1:
        seq = ", ".join(f"{_fmt_date(b['date'])} — {b['area'].lower()} ({b['good_units']} годных)" for b in bottlenecks)
        findings.append({"severity": "info", "kind": "bottleneck", "title": "Узкое место смещается",
                         "details": f"Меньше всего годных кузовов: {seq}."})

    if len(plan_models):
        total = int(plan_models["plan_month_units"].sum())
        goal = int(tg["monthly_output_min"])
        shifts = int(tg.get("shifts_per_day", plant["schedule"]["shifts_per_day"]))
        per_shift = int(lines["plan_units"].max()) if len(lines) else int(plant["rates"]["plan_units_per_shift"])
        cap22 = per_shift * shifts * 22
        if total < goal:
            findings.append({"severity": "warning", "kind": "plan",
                             "title": f"План по моделям {total:,} против цели {goal:,} в месяц".replace(",", " "),
                             "details": f"Не хватает {goal - total:,} машин. ".replace(",", " ") +
                                        f"При {per_shift} машинах за смену и {shifts} сменах 22 рабочих дня дают "
                                        f"{cap22:,} — для {goal:,} нужно около {goal / (per_shift * shifts):.0f} дней "
                                        f"без потерь.".replace(",", " ")})

    severity_order = {"critical": 0, "warning": 1, "info": 2}
    findings.sort(key=lambda f: severity_order[f["severity"]])
    return {
        "tables": {k: v.to_dict("records") for k, v in tables.items()},
        "downtime": dt_rows,
        "kpi_rows": kpi_rows,
        "reconciliation": recon,
        "bottlenecks": bottlenecks,
        "targets": tg,
        "scheme": parsed["scheme"],
        "findings": findings,
        "warnings": warnings,
        "timezone": TZ_NAME,
    }


def import_files(files: list[tuple[str, bytes]]) -> dict[str, Any]:
    parsed = read_files(files)
    if not parsed["tables"]:
        raise ValueError("В файлах не найдено ни одной таблицы в формате данных организаторов")
    result = analyze(parsed)
    result["files"] = [name for name, _ in files]
    result["rows"] = {k: len(v) for k, v in parsed["tables"].items()}
    return result
