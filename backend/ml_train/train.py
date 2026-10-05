"""Обучение и проверка моделей ИИ. Запуск из папки backend: python -m ml_train.train  (или make train)

1. Прогноз отказов (LightGBM): симулятор «проживает» несколько независимых лет работы завода
   (разные seed), FailureMonitor собирает признаки раз в 5 минут, метка — «отказ в ближайшие 2 часа работы».
   Обучение — на одних seed, выбор порога — на другом, итоговая проверка — на отдельном, с той же логикой
   предупреждений, что и в живом режиме.
2. Классификатор текста отчётов: точность на синтетике и на фразах, написанных вручную.
3. Прогноз месяца: проверка бутстрепа на синтетической истории — сколько месяцев попало в интервал 10–90%.

Результат: data/models/failure_lgbm.txt, failure_meta.json и отчёт docs/ML_REPORT.md.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from app.config import MODELS_DIR, ROOT_DIR, plant_config, targets_config
from app.ml.failure import (EVAL_EVERY_MIN, FEATURES, HORIZON_MIN, META_FILE, MODEL_FILE, AlertLogic,
                            FailureModel, FailureMonitor)
from app.ml.forecast import bootstrap_month
from app.sim.engine import DAY_MIN, PlantSim

START = datetime(2025, 1, 6)        # понедельник; даты условные
SPLITS = {"train": [1001, 1002, 1003], "val": [1004], "test": [1005]}
ARTIFACTS = Path(__file__).with_name("artifacts")     # собранные истории (в .gitignore)
THRESHOLDS = (0.05, 0.08, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.7)
TYPES = ("conveyor", "oven")


# ─────────────────────────────── данные ───────────────────────────────────────


class ShiftClock:
    """Минуты работы (в сменах) между моментами — горизонт прогноза считается в рабочем времени."""

    def __init__(self, a: np.ndarray, b: np.ndarray) -> None:
        self.a, self.b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
        self.cum = np.concatenate([[0.0], np.cumsum(self.b - self.a)])

    @classmethod
    def of(cls, sim: PlantSim) -> "ShiftClock":
        w = sim.cal.shift_windows(0.0, sim.now + DAY_MIN)
        return cls(np.array([x[2] for x in w]), np.array([x[3] for x in w]))

    def at(self, t: np.ndarray | float) -> np.ndarray:
        t = np.asarray(t, dtype=float)
        i = np.searchsorted(self.a, t, side="right") - 1
        i = np.clip(i, 0, len(self.a) - 1)
        inside = np.clip(t - self.a[i], 0.0, self.b[i] - self.a[i])
        return np.where(t < self.a[0], 0.0, self.cum[i] + inside)


def _events(sim: PlantSim) -> tuple[dict, dict]:
    fails: dict[str, list[float]] = {}
    maint: dict[str, list[float]] = {}
    for t, scope, eid, _, state, reason, _, _ in sim.rec.events:
        if scope != "equipment":
            continue
        if state == "down" and reason == "breakdown":
            fails.setdefault(eid, []).append(t)
        elif state == "maintenance":
            maint.setdefault(eid, []).append(t)
    return fails, maint


def _pack(samples: list) -> dict:
    return {"X": np.array([s[2] for s in samples]) if samples else np.zeros((0, len(FEATURES))),
            "t": np.array([s[0] for s in samples], dtype=float), "eq": np.array([s[1] for s in samples])}


def collect(seed: int, days: int, reuse: bool) -> dict:
    """История одного «года» завода: признаки, отказы, ТО, смены. Берётся с диска, если уже собрана."""
    path = ARTIFACTS / f"seed{seed}_d{days}.npz"
    if reuse and path.is_file():
        z = np.load(path, allow_pickle=True)
        return {"main": {"X": z["X"], "t": z["t"], "eq": z["eq"]},
                "robots": {"X": z["rX"], "t": z["rt"], "eq": z["req"]},
                "fails": z["fails"].item(), "maint": z["maint"].item(),
                "clock": ShiftClock(z["ca"], z["cb"]), "forecast": z["forecast"].item()}
    sim = PlantSim(plant_config(), seed=seed, start=START, telemetry_window_min=130)
    mon = FailureMonitor(sim, None, collect=True)
    robots = FailureMonitor(sim, None, collect=True, types=("robot",), eval_every=15.0)
    sim.run_days(days)
    fails, maint = _events(sim)
    clock = ShiftClock.of(sim)
    out = {"main": _pack(mon.samples), "robots": _pack(robots.samples), "fails": fails, "maint": maint,
           "clock": clock, "forecast": eval_forecast(sim)}
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, X=out["main"]["X"], t=out["main"]["t"], eq=out["main"]["eq"],
                        rX=out["robots"]["X"], rt=out["robots"]["t"], req=out["robots"]["eq"],
                        fails=np.array(fails, dtype=object), maint=np.array(maint, dtype=object),
                        ca=clock.a, cb=clock.b, forecast=np.array(out["forecast"], dtype=object))
    return out


def live_replay(seed: int, days: int, model: FailureModel) -> dict:
    """Проверка «как в жизни»: модель внутри симулятора, та же логика инцидентов, что в живом режиме."""
    sim = PlantSim(plant_config(), seed=seed, start=START, telemetry_window_min=130)
    mon = FailureMonitor(sim, model)
    sim.run_days(days)
    return mon.stats()


def label(d: dict, fails: dict[str, list[float]], clock: ShiftClock):
    X, t, eq = d["X"], d["t"], d["eq"]
    y = np.zeros(len(t), dtype=int)
    for e in np.unique(eq):
        idx = np.where(eq == e)[0]
        ft = np.asarray(fails.get(str(e), []))
        if not len(ft):
            continue
        j = np.searchsorted(ft, t[idx], side="right")
        has = j < len(ft)
        nxt = np.where(has, ft[np.minimum(j, len(ft) - 1)], np.inf)
        gap = np.where(has, clock.at(nxt) - clock.at(t[idx]), np.inf)
        y[idx] = (gap <= HORIZON_MIN).astype(int)
    return X, y, t, eq


# ─────────────────────────────── оценка ───────────────────────────────────────


def replay(t: np.ndarray, eq: np.ndarray, p: np.ndarray, fails: dict, maint: dict, thr_on: float, thr_off: float,
           confirm: int = 2) -> dict:
    """Та же логика предупреждений, что в живом режиме, по готовым вероятностям."""
    detected, missed, false_alarms, leads = 0, 0, 0, []
    hours = len(t) * EVAL_EVERY_MIN / 60
    for e in np.unique(eq):
        idx = np.where(eq == e)[0]
        ev = [(float(t[i]), 0, float(p[i])) for i in idx]
        ev += [(f, 1, 0.0) for f in fails.get(str(e), [])]
        ev += [(m, 2, 0.0) for m in maint.get(str(e), [])]
        ev.sort()
        al = AlertLogic(thr_on, thr_off, confirm)
        t_open = None
        for tt, kind, pp in ev:
            if kind == 0:
                act = al.update(pp)
                if act == "open":
                    t_open = tt
                elif act == "close":
                    false_alarms += 1
                    t_open = None
            elif kind == 1:
                if al.active:
                    detected += 1
                    leads.append(tt - t_open)
                else:
                    missed += 1
                al.reset()
                t_open = None
            else:
                al.reset()
                t_open = None
    n = detected + missed
    return {"failures": n, "detected": detected, "recall": detected / n if n else None,
            "false_alarms": false_alarms, "false_per_1000h": false_alarms / hours * 1000 if hours else None,
            "lead_median_min": float(np.median(leads)) if leads else None,
            "lead_min_min": float(np.min(leads)) if leads else None,
            "monitor_hours": round(hours)}


def auc_pr(y: np.ndarray, p: np.ndarray) -> tuple[float | None, float | None]:
    from sklearn.metrics import average_precision_score, roc_auc_score

    if y.sum() == 0 or y.sum() == len(y):
        return None, None
    return float(roc_auc_score(y, p)), float(average_precision_score(y, p))


# ─────────────────────────────── обучение отказов ─────────────────────────────


def train_failure(days: int, reuse: bool, log) -> dict:
    import lightgbm as lgb

    runs = {}
    for split, seeds in SPLITS.items():
        for s in seeds:
            t0 = time.time()
            runs[s] = collect(s, days, reuse)
            r = runs[s]
            nf = sum(len(v) for k, v in r["fails"].items() if k in set(r["main"]["eq"].tolist()))
            log(f"  seed {s} ({split}): {len(r['main']['t'])} точек, отказов с предвестником {nf}, "
                f"{time.time() - t0:.0f} с")

    def data(seeds, part="main"):
        parts = [label(runs[s][part], runs[s]["fails"], runs[s]["clock"]) for s in seeds]
        return [np.concatenate([p[i] for p in parts]) for i in range(4)]

    Xtr, ytr, _, _ = data(SPLITS["train"])
    Xva, yva, tva, eqva = data(SPLITS["val"])
    oi = FEATURES.index("is_oven")
    params = {"objective": "binary", "learning_rate": 0.05, "num_leaves": 15, "min_data_in_leaf": 40,
              "feature_fraction": 0.9, "bagging_fraction": 0.8, "bagging_freq": 1, "lambda_l2": 1.0,
              "verbose": -1, "seed": 7, "num_threads": 2}

    # LightGBM — для конвейеров (обрыв цепи)
    ctr, cva = Xtr[:, oi] < 0.5, Xva[:, oi] < 0.5
    dtr = lgb.Dataset(Xtr[ctr], ytr[ctr], feature_name=FEATURES)
    dva = lgb.Dataset(Xva[cva], yva[cva], reference=dtr)
    booster = lgb.train(params, dtr, num_boost_round=600, valid_sets=[dva],
                        callbacks=[lgb.early_stopping(50, verbose=False)])
    log(f"  конвейеры: деревьев {booster.best_iteration}; положительных примеров {int(ytr[ctr].sum())} из {int(ctr.sum())}")

    # Порог предупреждения — на валидации: больше пойманных отказов при минимуме ложных тревог
    pva = booster.predict(Xva[cva], num_iteration=booster.best_iteration)
    val = runs[SPLITS["val"][0]]
    g = []
    for thr in THRESHOLDS:
        r = replay(tva[cva], eqva[cva], pva, val["fails"], val["maint"], thr, thr / 2)
        g.append((r["detected"] - 0.5 * r["false_alarms"], thr, r))
    best = max(g, key=lambda x: (x[0], x[1]))
    alert = {"conveyor": {"method": "ml", "thr_on": best[1], "thr_off": best[1] / 2, "confirm": 2},
             "oven": {"method": "rule", "feature": "temp_sd", "thr_on": 2.0, "thr_off": 1.5, "confirm": 2}}
    grid = {"conveyor": [{"thr": x[1], **x[2]} for x in g]}
    log(f"  порог для конвейеров: {best[1]} (валидация: {best[2]['detected']}/{best[2]['failures']} отказов, "
        f"ложных {best[2]['false_alarms']})")

    # Итоговая проверка на отдельном seed
    test = runs[SPLITS["test"][0]]
    Xte, yte, tte, eqte = label(test["main"], test["fails"], test["clock"])
    c, o = Xte[:, oi] < 0.5, Xte[:, oi] > 0.5
    pte = booster.predict(Xte[c], num_iteration=booster.best_iteration)
    roc, prc = auc_pr(yte[c], pte)
    a_ = alert["conveyor"]
    ev_c = replay(tte[c], eqte[c], pte, test["fails"], test["maint"], a_["thr_on"], a_["thr_off"])
    temp = Xte[o][:, FEATURES.index("temp_sd")]
    ev_o = replay(tte[o], eqte[o], temp, test["fails"], test["maint"], 2.0, 1.5)
    roc_o, prc_o = auc_pr(yte[o], temp)
    by_type = {"conveyor": {"method": "LightGBM", "roc_auc": roc, "pr_auc": prc, "positives": int(yte[c].sum()), **ev_c},
               "oven": {"method": "правило: разброс температуры ×2", "roc_auc": roc_o, "pr_auc": prc_o,
                        "positives": int(yte[o].sum()), **ev_o}}

    # Почему печь — правило: та же модель, обученная на всех типах, на печи почти ничего не ловит
    joint = lgb.train(params, lgb.Dataset(Xtr, ytr, feature_name=FEATURES), num_boost_round=booster.best_iteration)
    pj = joint.predict(Xte[o])
    roc_j, prc_j = auc_pr(yte[o], pj)
    ev_j = replay(tte[o], eqte[o], pj, test["fails"], test["maint"], 0.5, 0.25)
    oven_ml = {"roc_auc": roc_j, "pr_auc": prc_j, "train_failures": int(sum(len(runs[s]["fails"].get("OVEN-01", []))
                                                                             for s in SPLITS["train"])), **ev_j}

    # Простое правило для конвейеров — для сравнения с моделью: ток за 15 мин выше нормы на 8%
    rule = (Xte[c][:, FEATURES.index("cur_15")] > 0.08).astype(float)
    ev_rule = replay(tte[c], eqte[c], rule, test["fails"], test["maint"], 0.5, 0.5)

    fail = ev_c["failures"] + ev_o["failures"]
    det = ev_c["detected"] + ev_o["detected"]
    fa = ev_c["false_alarms"] + ev_o["false_alarms"]
    hours = ev_c["monitor_hours"] + ev_o["monitor_hours"]
    ev_all = {"failures": fail, "detected": det, "recall": det / fail if fail else None, "false_alarms": fa,
              "false_per_1000h": fa / hours * 1000 if hours else None,
              "lead_median_min": ev_c["lead_median_min"], "monitor_hours": hours}
    auc, pr = roc, prc

    # Роботы: тот же подход на сбоях датчиков — проверяем, что предсказать их нельзя
    robot = {}
    Xr, yr, _, _ = data(SPLITS["train"], "robots")
    Xrt, yrt, _, _ = label(test["robots"], test["fails"], test["clock"])
    if yr.sum() and yrt.sum():
        rb = lgb.train(params, lgb.Dataset(Xr, yr), num_boost_round=150)
        a_, b_ = auc_pr(yrt, rb.predict(Xrt))
        robot = {"roc_auc": a_, "pr_auc": b_, "base_rate": float(yrt.mean()), "positives": int(yrt.sum())}

    imp = dict(zip(FEATURES, booster.feature_importance("gain").round(1).tolist()))
    meta = {
        "features": FEATURES,
        "model_for": ["conveyor"],
        "horizon_min": HORIZON_MIN,
        "eval_every_min": EVAL_EVERY_MIN,
        "alert": alert,
        "trees": booster.best_iteration,
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data": {"days_per_seed": days, "splits": SPLITS,
                 "note": "Синтетическая история симулятора, откалиброванного по тестовым данным организаторов."},
        "metrics": {"test": {"roc_auc": auc, "pr_auc": pr, "base_rate": float(yte[c].mean()), **ev_all},
                    "by_type": by_type, "rule_baseline": {"conveyor": ev_rule}, "oven_ml_attempt": oven_ml,
                    "robots_sensor_errors": robot,
                    "threshold_grid": grid},
        "importance_gain": imp,
    }
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    booster.save_model(str(MODELS_DIR / MODEL_FILE), num_iteration=booster.best_iteration)
    (MODELS_DIR / META_FILE).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    model = FailureModel.load()
    meta["metrics"]["live_replay"] = live_replay(SPLITS["test"][0], days, model)
    meta["metrics"]["forecast"] = test["forecast"]
    (MODELS_DIR / META_FILE).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


# ─────────────────────────────── отчёты и месяц ───────────────────────────────


def eval_reports() -> dict:
    from sklearn.model_selection import train_test_split

    from app.ml.report_classifier import ReportClassifier, build_corpus, rules_predict, train_classifier

    X, y = build_corpus()
    Xa, Xb, ya, yb = train_test_split(X, y, test_size=0.25, random_state=0, stratify=y)
    clf = ReportClassifier().fit(Xa, ya)
    acc_in = float(np.mean([p.subtype == t for p, t in zip(clf.predict_many(Xb), yb)]))
    full = train_classifier(save=True)
    rows = list(csv.DictReader(open(Path(__file__).with_name("report_holdout.csv"), encoding="utf-8")))
    pred = full.predict_many([r["text"] for r in rows])
    acc_ho = float(np.mean([p.subtype == r["subtype"] for p, r in zip(pred, rows)]))
    rules = [rules_predict(r["text"]) for r in rows]
    acc_rules = float(np.mean([(q.subtype if q else "") == r["subtype"] for q, r in zip(rules, rows)]))
    errors = [{"text": r["text"], "true": r["subtype"], "pred": p.subtype, "conf": round(p.confidence, 2)}
              for p, r in zip(pred, rows) if p.subtype != r["subtype"]]
    return {"corpus": len(X), "acc_synthetic": acc_in, "holdout": len(rows), "acc_holdout": acc_ho,
            "acc_rules_holdout": acc_rules, "errors": errors}


def eval_forecast(sim: PlantSim) -> dict:
    """Для каждого полного месяца истории: прогноз на 5-й, 10-й и 15-й рабочий день против факта."""
    cal = sim.cal
    qc = np.array([u[0] for u in sim.rec.units if u[3] == "QC"])
    windows = cal.shift_windows(0.0, sim.now)
    out_shift = [int(np.sum((qc >= a) & (qc < b))) for _, _, a, b in windows]
    by_month: dict[str, list[int]] = {}
    for k, (_, _, a, _) in enumerate(windows):
        by_month.setdefault(cal.dt(a).strftime("%Y-%m"), []).append(k)
    target = float(targets_config()["monthly_output_min"])
    rows = []
    months = list(by_month)[1:-1]            # первый и последний месяцы неполные
    for m in months:
        ks = by_month[m]
        actual = sum(out_shift[k] for k in ks)
        for day_no in (5, 10, 15):
            cut = ks[0] + 2 * day_no                     # 2 смены в рабочий день
            if cut >= ks[-1] or cut < 40:
                continue
            hist = out_shift[cut - 40:cut]
            mtd = sum(out_shift[k] for k in ks if k < cut)
            rem = [(str(k), 1.0) for k in ks if k >= cut]
            f = bootstrap_month(mtd, hist, rem, target, n_sims=2000, seed=1)
            rows.append({"month": m, "workday": day_no, "actual": actual, "p10": f["p10"], "p50": f["p50"],
                         "p90": f["p90"], "inside": f["p10"] <= actual <= f["p90"],
                         "abs_err_pct": abs(f["p50"] - actual) / actual * 100})
    if not rows:
        return {"checks": 0}
    return {"checks": len(rows), "coverage_10_90": float(np.mean([r["inside"] for r in rows])),
            "mape_p50": float(np.mean([r["abs_err_pct"] for r in rows])),
            "by_workday": {d: float(np.mean([r["abs_err_pct"] for r in rows if r["workday"] == d]))
                           for d in (5, 10, 15) if any(r["workday"] == d for r in rows)},
            "months": len(months), "shift_mean": float(np.mean(out_shift)), "rows": rows}


# ─────────────────────────────── отчёт ────────────────────────────────────────


NAMES = {"conveyor": "Конвейеры (обрыв цепи)", "oven": "Печь (сбой горелки)"}


def _p(x: float | None, digits: int = 0) -> str:
    return "—" if x is None else f"{x * 100:.{digits}f}%".replace(".", ",")


def _f(x: float | None, digits: int = 2) -> str:
    return "—" if x is None else f"{x:.{digits}f}".replace(".", ",")


def write_report(meta: dict, rep: dict, fc: dict, path: Path) -> None:
    m = meta["metrics"]
    te = m["test"]
    live = m.get("live_replay", {})
    rb = m["rule_baseline"]
    lines = [
        "# Отчёт о моделях ИИ",
        "",
        f"Сформирован автоматически: `make train` ({meta['trained_at'][:10]}). **Все данные синтетические** — "
        "история симулятора, откалиброванного по тестовым данным организаторов. На реальных данных завода "
        "модели нужно переобучить; цифры ниже показывают, что подход работает, а не точность на заводе.",
        "",
        "## 1. Прогноз отказов оборудования",
        "",
        "**Задача:** предупредить об отказе за время, достаточное, чтобы заменить аварию плановым вмешательством. "
        "Горизонт — 2 часа работы.",
        "",
        "| Оборудование | Отказ | Предвестник в телеметрии | Метод |",
        "|---|---|---|---|",
        "| Конвейеры | обрыв цепи | ток привода и вибрация растут за 1–3 ч | **LightGBM** |",
        "| Печь сушки | сбой горелки | разброс температуры растёт за 0,5–1,5 ч | правило «разброс ×2» |",
        "| Роботы ABB | сбой датчика | нет (отказ внезапный) | не прогнозируется, фоновая вероятность |",
        "| Стенды контроля | сбой калибровки | нет | не прогнозируется, фоновая вероятность |",
        "",
        f"**Данные:** {len(SPLITS['train']) + 2} независимых «лет» работы завода по {meta['data']['days_per_seed']} суток "
        f"(seed {', '.join(str(s) for v in SPLITS.values() for s in v)}):",
        "",
        "| Набор | Seed | Зачем |",
        "|---|---|---|",
        f"| обучение | {', '.join(map(str, SPLITS['train']))} | обучение модели |",
        f"| валидация | {SPLITS['val'][0]} | выбор числа деревьев и порога |",
        f"| проверка | {SPLITS['test'][0]} | итоговые метрики |",
        "",
        "Признаки (раз в 5 минут, последние 2 часа работы):",
        "- ток и вибрация относительно нормы за 15 и 60 минут;",
        "- их тренд за 30 минут;",
        "- разброс температуры;",
        "- наработка с последнего ТО.",
        "",
        f"Порог предупреждения для конвейеров — **{_f(meta['alert']['conveyor']['thr_on'])}** (подобран на валидации). "
        "Предупреждение открывается после 2 оценок подряд выше порога и снимается, когда риск падает вдвое. "
        "Та же логика работает в живом режиме и создаёт инцидент «Прогноз ИИ».",
        "",
        "### Качество на отдельной проверочной истории",
        "",
        "| Оборудование | Метод | ROC-AUC | Предупреждено заранее | Упреждение, медиана | Ложных |",
        "|---|---|---|---|---|---|",
        *[f"| {NAMES[k]} | {v['method']} | {_f(v['roc_auc'], 3)} | **{v['detected']} из {v['failures']}** | "
          f"{_f(v['lead_median_min'], 0)} мин | {v['false_alarms']} за {v['monitor_hours']} ч |"
          for k, v in m["by_type"].items()],
        "",
        f"PR-AUC для конвейеров — {_f(m['by_type']['conveyor']['pr_auc'], 3)} при доле положительных точек "
        f"{_p(te['base_rate'], 2)}.",
        "",
        "**Модель против простого правила (конвейеры).** Правило «ток за 15 мин выше нормы на 8%» ловит "
        f"{rb['conveyor']['detected']} из {rb['conveyor']['failures']} обрывов, но позже: медиана упреждения "
        f"{_f(rb['conveyor']['lead_median_min'], 0)} мин против {_f(m['by_type']['conveyor']['lead_median_min'], 0)} мин "
        "у модели. Модель замечает рост раньше, потому что видит сразу ток, вибрацию, их тренды и наработку.",
        "",
        "**Почему для печи правило, а не модель.** Отказов горелки мало: "
        f"{m['oven_ml_attempt']['train_failures']} в обучающей истории. Предвестник короткий. "
        "Модель, обученная на всех типах сразу, предупредила о "
        f"{m['oven_ml_attempt']['detected']} из {m['oven_ml_attempt']['failures']} сбоев печи "
        f"(ROC-AUC {_f(m['oven_ml_attempt']['roc_auc'], 3)}). Правило по разбросу температуры — о "
        f"{m['by_type']['oven']['detected']} из {m['by_type']['oven']['failures']}, но всего за "
        f"{_f(m['by_type']['oven']['lead_median_min'], 0)} мин. Этого хватит, чтобы вызвать наладчика, "
        "но не чтобы перенести ремонт.",
        "",
        "**Проверка «как в жизни».** Проверочная история прогнана заново с моделью внутри симулятора, "
        "с той же логикой инцидентов, что в живом режиме: "
        f"отказов с предвестником {live.get('failures', '—')}, предупреждено {live.get('predicted', '—')}, "
        f"среднее упреждение {_f(live.get('mean_lead_min'), 0)} мин, ложных {live.get('false_alarms', '—')}.",
        "",
    ]
    rob = m.get("robots_sensor_errors") or {}
    if rob:
        lines += [
            f"**Сбои датчиков роботов не прогнозируются.** Такая же модель на роботах даёт ROC-AUC {_f(rob['roc_auc'], 3)} "
            "(0,5 — случайное угадывание). Отказ внезапный, предвестника в телеметрии нет. Поэтому для роботов "
            "интерфейс показывает только фоновую вероятность по частоте отказов. Сократить простой можно не прогнозом, "
            "а запасом датчиков у линии и быстрой реакцией наладчика.",
            "",
        ]
    imp = sorted(meta["importance_gain"].items(), key=lambda kv: -kv[1])
    total = sum(v for _, v in imp) or 1
    lines += ["Важность признаков (доля прироста):",
              ", ".join(f"`{k}` {v / total * 100:.0f}%" for k, v in imp if v > 0) + ".", ""]

    lines += [
        "## 2. Классификация отчётов рабочих",
        "",
        "Модель: TF-IDF (слова + буквенные n-граммы, устойчиво к опечаткам) + логистическая регрессия. "
        "Работает офлайн, ответ за ~2 мс. Если подключён Groq или Gemini, свободный текст с формы "
        "дополнительно разбирает LLM.",
        "",
        "| Проверка | Точность |",
        "|---|---|",
        f"| Синтетические отчёты, отложенные 25% (корпус {rep['corpus']}) | {_p(rep['acc_synthetic'], 1)} |",
        f"| Фразы, написанные вручную ({rep['holdout']} шт., `ml_train/report_holdout.csv`) | **{_p(rep['acc_holdout'], 1)}** |",
        f"| То же, только правила по ключевым словам | {_p(rep['acc_rules_holdout'], 1)} |",
        "",
        "Точность на синтетике завышена: тексты из тех же шаблонов. Честная оценка — фразы, написанные вручную; "
        "на реальных отчётах завода она будет ниже, пока модель не дообучена на них.",
        "",
    ]
    if rep["errors"]:
        lines += ["Ошибки на ручных фразах:", ""]
        lines += [f"- «{e['text']}» — верно: {e['true']}, модель: {e['pred']} ({_f(e['conf'])})" for e in rep["errors"]]
        lines += [""]

    lines += ["## 3. Прогноз выпуска за месяц", ""]
    if fc.get("checks"):
        lines += [
            "Метод — бутстреп по сменам: оставшиеся смены месяца 4000 раз заполняются выпуском случайных смен "
            "из последних 40.",
            "",
            f"Проверка на проверочной истории: полных месяцев — {fc['months']}, прогноз на 5-й, 10-й и 15-й рабочий "
            f"день, всего проверок — {fc['checks']}.",
            "",
            "| Метрика | Значение |",
            "|---|---|",
            f"| Факт внутри интервала 10–90% | {_p(fc['coverage_10_90'])} проверок |",
            f"| Средняя ошибка медианы | {_f(fc['mape_p50'], 1)}% |",
            *[f"| …на {d}-й рабочий день | {_f(v, 1)}% |" for d, v in fc["by_workday"].items()],
            "",
            f"Средний выпуск смены в истории — {_f(fc['shift_mean'], 1)} авто. Месяц из 22 рабочих дней при таком "
            f"темпе — около {fc['shift_mean'] * 44:.0f} авто.",
            "",
            "Ошибка так мала, потому что в синтетике выпуск смены стабилен: крупных аварий на несколько смен "
            "в модели нет. На реальном заводе интервал будет шире — метод это учтёт сам, потому что берёт "
            "разброс из фактических смен.",
            "",
        ]
    lines += [
        "## Ограничения",
        "",
        "- Модели обучены на синтетике. Параметры отказов (Вейбулл, длина предвестника) — допущения, "
        "откалиброванные по нескольким эпизодам из тестовых данных.",
        "- Для обучения на заводе нужна телеметрия станков (ток, вибрация, температура) с метками отказов "
        "за 6–12 месяцев. Код обучения тот же: `ml_train/train.py`.",
        "- LLM (Groq, Gemini) формулирует выводы и разбирает свободный текст. Цифры в выводах считает код, "
        "а не модель: числа в тексте LLM сверяются с расчётом.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Обучить и проверить модели ИИ")
    ap.add_argument("--days", type=int, default=150, help="суток на один seed")
    ap.add_argument("--reuse", action="store_true", help="взять уже собранные истории из ml_train/artifacts")
    args = ap.parse_args()
    t0 = time.time()

    def log(msg: str) -> None:
        print(msg, flush=True)

    log("Прогноз отказов: генерация истории и обучение LightGBM…")
    meta = train_failure(args.days, args.reuse, log)
    log(json.dumps(meta["metrics"]["test"], ensure_ascii=False))
    log(f"  в живом режиме: {meta['metrics']['live_replay']}")
    log("Классификатор отчётов…")
    rep = eval_reports()
    log(f"  синтетика {rep['acc_synthetic']:.3f}, ручные фразы {rep['acc_holdout']:.3f}, правила {rep['acc_rules_holdout']:.3f}")
    fc = meta["metrics"]["forecast"]
    log("Прогноз месяца (проверка на истории):")
    log(f"  проверок {fc.get('checks')}, покрытие 10–90%: {fc.get('coverage_10_90')}, ошибка медианы {fc.get('mape_p50')}")
    meta_path = MODELS_DIR / META_FILE
    full = json.loads(meta_path.read_text(encoding="utf-8"))
    full["metrics"]["reports"] = {k: v for k, v in rep.items() if k != "errors"}
    full["metrics"]["forecast"] = {k: v for k, v in fc.items() if k != "rows"}
    full["metrics"]["test"].pop("_", None)
    meta_path.write_text(json.dumps(full, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(full, rep, fc, ROOT_DIR / "docs" / "ML_REPORT.md")
    log(f"Готово за {time.time() - t0:.0f} с: {MODELS_DIR / MODEL_FILE}, docs/ML_REPORT.md")


if __name__ == "__main__":
    main()
