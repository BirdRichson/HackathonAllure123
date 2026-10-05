"""Прогноз отказов оборудования по телеметрии.

Что прогнозируем: отказ в ближайшие 2 часа работы (`HORIZON_MIN`) у оборудования с износовыми отказами.
- Конвейеры, обрыв цепи — модель LightGBM: за 1–3 часа до обрыва растут ток привода и вибрация.
- Печь сушки, сбой горелки — правило «разброс температуры вдвое выше нормы»: предвестник короткий
  (полчаса–полтора), а отказов в истории единицы — модели не на чем учиться, правило работает лучше
  (сравнение — в docs/ML_REPORT.md).
- Сбои датчиков роботов и калибровки стендов случайны, предвестника нет — их не прогнозируем,
  показываем фоновую вероятность по частоте отказов.

Как работает:
- `FailureMonitor` подписан на поток телеметрии симулятора (1 запись в минуту на станок), держит последние
  2 часа по каждому станку и раз в 5 минут считает признаки и риск;
- признаки (`compute_features`) одинаковые при обучении и в живом режиме — обучение использует этот же класс;
- предупреждение открывается, когда риск дважды подряд выше порога, и закрывается при отказе, ТО или
  снижении риска (`AlertLogic`) — так же, как при оценке модели в backend/ml_train/train_failure.py.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from app.config import MODELS_DIR

PREDICTABLE_TYPES = ("conveyor", "oven")
HORIZON_MIN = 120.0
EVAL_EVERY_MIN = 5.0
BUFFER_MIN = 120
MIN_ROWS = 30

FEATURES = ["cur_15", "cur_60", "vib_15", "vib_60", "cur_slope", "vib_slope", "temp_sd", "since_to", "is_oven"]
MODEL_FILE = "failure_lgbm.txt"
META_FILE = "failure_meta.json"


def _slope(y: np.ndarray) -> float:
    """Наклон линейного тренда, изменение за 10 минут."""
    n = len(y)
    if n < 3:
        return 0.0
    x = np.arange(n, dtype=float)
    x -= x.mean()
    return float((x * (y - y.mean())).sum() / (x * x).sum() * 10.0)


def compute_features(rows: np.ndarray, base: dict, since_to_frac: float, is_oven: bool) -> np.ndarray:
    """rows: [[t, температура, вибрация, ток], …] за последние ≤120 минут работы, по возрастанию времени."""
    temp, vib, cur = rows[:, 1], rows[:, 2], rows[:, 3]
    cur_rel = cur / float(base["current"][0]) - 1.0
    vib_rel = vib / float(base["vibration"][0]) - 1.0
    return np.array([
        cur_rel[-15:].mean(), cur_rel[-60:].mean(),
        vib_rel[-15:].mean(), vib_rel[-60:].mean(),
        _slope(cur_rel[-30:]), _slope(vib_rel[-30:]),
        temp[-30:].std() / float(base["temperature"][1]),
        since_to_frac, 1.0 if is_oven else 0.0,
    ], dtype=float)


def factor_text(name: str, v: float) -> tuple[str, str] | None:
    """Человеческая подпись признака и его значения — для карточки риска."""
    if name == "cur_15":
        return "Ток привода, 15 мин", f"{v * 100:+.0f}% к норме"
    if name == "cur_60":
        return "Ток привода, час", f"{v * 100:+.0f}% к норме"
    if name == "vib_15":
        return "Вибрация, 15 мин", f"{v * 100:+.0f}% к норме"
    if name == "vib_60":
        return "Вибрация, час", f"{v * 100:+.0f}% к норме"
    if name == "cur_slope":
        return "Рост тока", f"{v * 100:+.1f}% за 10 мин".replace(".", ",")
    if name == "vib_slope":
        return "Рост вибрации", f"{v * 100:+.1f}% за 10 мин".replace(".", ",")
    if name == "temp_sd":
        return "Разброс температуры", f"×{v:.1f} к норме".replace(".", ",")
    if name == "since_to":
        return "Наработка с ТО", f"{v * 100:.0f}% интервала"
    return None


# ─────────────────────────────── модель ───────────────────────────────────────


class FailureModel:
    def __init__(self, booster: Any, meta: dict) -> None:
        self.booster = booster
        self.meta = meta

    def cfg(self, eq_type: str) -> dict:
        return self.meta["alert"].get(eq_type) or self.meta["alert"]["conveyor"]

    def method(self, eq_type: str) -> str:
        """ml — вероятность от LightGBM; rule — значение признака против порога."""
        return self.cfg(eq_type).get("method", "ml")

    def alert_logic(self, eq_type: str) -> "AlertLogic":
        """Пороги предупреждения — свои для каждого типа оборудования (подобраны на валидации)."""
        a = self.cfg(eq_type)
        return AlertLogic(float(a["thr_on"]), float(a["thr_off"]), int(a["confirm"]))

    def score(self, eq_type: str, x: np.ndarray) -> float:
        a = self.cfg(eq_type)
        if a.get("method") == "rule":
            return float(x[FEATURES.index(a["feature"])])
        return float(self.predict(x)[0])

    @classmethod
    def load(cls, models_dir=MODELS_DIR) -> "FailureModel | None":
        mf, jf = models_dir / MODEL_FILE, models_dir / META_FILE
        if not (mf.is_file() and jf.is_file()):
            return None
        try:
            import lightgbm as lgb

            booster = lgb.Booster(model_file=str(mf))
            meta = json.loads(jf.read_text(encoding="utf-8"))
            if meta.get("features") != FEATURES:
                return None
            return cls(booster, meta)
        except Exception:
            return None

    def predict(self, X: np.ndarray) -> np.ndarray:
        return self.booster.predict(np.atleast_2d(X), num_threads=1)

    def factors(self, x: np.ndarray, top: int = 3, eq_type: str = "conveyor") -> list[dict]:
        """Главные причины риска: вклад признаков (SHAP-значения LightGBM), только повышающие риск."""
        a = self.cfg(eq_type)
        if a.get("method") == "rule":
            i = FEATURES.index(a["feature"])
            ft = factor_text(a["feature"], float(x[i]))
            return [{"feature": a["feature"], "label": ft[0], "value": ft[1], "weight": 1.0}] if ft else []
        contrib = self.booster.predict(np.atleast_2d(x), pred_contrib=True, num_threads=1)[0][:-1]
        order = np.argsort(-contrib)
        out = []
        for i in order:
            if contrib[i] <= 0.05 or FEATURES[i] == "is_oven":
                continue
            ft = factor_text(FEATURES[i], float(x[i]))
            if ft:
                out.append({"feature": FEATURES[i], "label": ft[0], "value": ft[1], "weight": round(float(contrib[i]), 3)})
            if len(out) >= top:
                break
        return out


@dataclass
class AlertLogic:
    """Гистерезис: открыть после `confirm` оценок подряд выше thr_on, закрыть ниже thr_off."""

    thr_on: float
    thr_off: float
    confirm: int = 2
    above: int = 0
    active: bool = False

    def update(self, p: float) -> str | None:
        if self.active:
            if p < self.thr_off:
                self.active, self.above = False, 0
                return "close"
            return None
        self.above = self.above + 1 if p >= self.thr_on else 0
        if self.above >= self.confirm:
            self.active = True
            return "open"
        return None

    def reset(self) -> None:
        self.active, self.above = False, 0


# ─────────────────────────────── монитор ──────────────────────────────────────


@dataclass
class Tracked:
    eq: Any
    base: dict
    is_oven: bool
    mode_text: str
    repair_min: float
    buf: deque = field(default_factory=lambda: deque(maxlen=BUFFER_MIN))
    last_eval: float = -1e9
    was_stopped: bool = False
    risk: float | None = None
    risk_t: float | None = None
    x: np.ndarray | None = None
    alert: AlertLogic | None = None
    alert_key: str | None = None
    alert_t: float | None = None


class FailureMonitor:
    """Следит за станками, считает риск отказа, открывает и закрывает предупреждения-инциденты."""

    def __init__(self, sim, model: FailureModel | None, *, incidents=None, active_from: float = 0.0,
                 collect: bool = False, types: tuple[str, ...] = PREDICTABLE_TYPES,
                 eval_every: float = EVAL_EVERY_MIN) -> None:
        self.sim = sim
        self.model = model
        self.incidents = incidents
        self.active_from = active_from
        self.collect = collect
        self.eval_every = eval_every
        self.samples: list[tuple[float, str, np.ndarray]] = []
        self.outcomes: list[dict] = []          # по каждому отказу: был ли прогноз и за сколько минут
        self.false_alarms = 0
        self.version = 0                        # растёт при каждом пересчёте — чтобы рассылать обновления
        self.on_change: list[Callable[[], None]] = []
        self.tracked: dict[str, Tracked] = {}
        for eq in sim.equipment.values():
            if eq.type not in types:
                continue
            modes = eq.tcfg.get("failure_modes") or []
            mode = modes[0] if modes else {}
            t = Tracked(eq, eq.tcfg["telemetry"], eq.type == "oven", mode.get("reason_text", "отказ"),
                        float((mode.get("repair_min") or {}).get("median", 0)))
            if model is not None:
                t.alert = model.alert_logic(eq.type)
            self.tracked[eq.id] = t
        sim.rec.listeners.append(self.on_record)

    # ── поток модели ──

    def on_record(self, kind: str, row: Any) -> None:
        if kind == "telemetry":
            tr = self.tracked.get(row[1])
            if tr is None:
                return
            tr.buf.append((row[0], row[2], row[3], row[4]))
            if row[0] - tr.last_eval >= self.eval_every - 1e-9:
                tr.last_eval = row[0]
                if row[0] >= self.active_from:
                    self._evaluate(tr, row[0])
        elif kind == "state" and row[1] == "equipment":
            tr = self.tracked.get(row[2])
            if tr is None:
                return
            t, state, reason = row[0], row[4], row[5]
            if state in ("down", "maintenance"):
                tr.was_stopped = True
                if state == "down" and reason == "breakdown":
                    self._on_failure(tr, t)
                elif state == "maintenance":
                    self._close_alert(tr, t, "Проведено плановое ТО — предупреждение снято.", outcome="maintenance")
            elif state == "running" and tr.was_stopped:
                # после ремонта или ТО отсчёт заново: старые значения больше не про это состояние
                tr.was_stopped = False
                tr.buf.clear()
                tr.risk, tr.x = None, None
                self.version += 1

    def _evaluate(self, tr: Tracked, t: float) -> None:
        if tr.eq.status != "ok" or len(tr.buf) < MIN_ROWS:
            return
        rows = np.asarray(tr.buf, dtype=float)
        x = compute_features(rows, tr.base, tr.eq.since_to_h / tr.eq.interval_h, tr.is_oven)
        if self.collect:
            self.samples.append((t, tr.eq.id, x))
        if self.model is None:
            return
        p = self.model.score(tr.eq.type, x)
        tr.risk, tr.risk_t, tr.x = p, t, x
        self.version += 1
        act = tr.alert.update(p) if tr.alert else None
        if act == "open":
            self._open_alert(tr, t, p)
        elif act == "close":
            self._close_alert(tr, t, "Риск снизился — предупреждение снято.", outcome="false_alarm")
        elif tr.alert and tr.alert.active and self.incidents is not None and tr.alert_key:
            self.incidents._open(tr.alert_key, tr.alert_t, "warning", "prediction", tr.eq.area_id, tr.eq.id,
                                 self._title(tr, p), self._details(tr, x))

    # ── предупреждения ──

    def _title(self, tr: Tracked, p: float) -> str:
        what = tr.mode_text[0].lower() + tr.mode_text[1:]
        if self.model and self.model.method(tr.eq.type) == "rule":
            return f"Признак отказа: {tr.eq.name} — возможен «{what}», разброс температуры ×{p:.1f} к норме".replace(".", ",")
        return f"Прогноз ИИ: {tr.eq.name} — риск «{what}» {p * 100:.0f}% в ближайшие 2 ч"

    def _details(self, tr: Tracked, x: np.ndarray) -> str:
        parts = [f"{f['label'].split(',')[0]} {f['value']}" for f in self.model.factors(x, eq_type=tr.eq.type)] \
            if self.model else []
        rec = ("Осмотрите цепь и натяжение при ближайшей возможности" if not tr.is_oven
               else "Проверьте горелку и электрод розжига при ближайшей возможности")
        head = (", ".join(parts) + ". ") if parts else ""
        return f"{head}{rec}: плановая остановка короче аварийной (ремонт после отказа — около {tr.repair_min:.0f} мин)."

    def _open_alert(self, tr: Tracked, t: float, p: float) -> None:
        tr.alert_t = t
        tr.alert_key = f"pred:{tr.eq.id}:{t:.1f}"
        if self.incidents is not None:
            self.incidents._open(tr.alert_key, t, "warning", "prediction", tr.eq.area_id, tr.eq.id,
                                 self._title(tr, p), self._details(tr, tr.x))

    def _close_alert(self, tr: Tracked, t: float, details: str, outcome: str) -> None:
        if tr.alert is None or not tr.alert.active:
            return
        tr.alert.reset()
        if outcome == "false_alarm":
            self.false_alarms += 1
        if self.incidents is not None and tr.alert_key:
            inc_id = self.incidents.by_key.get(tr.alert_key)
            old = self.incidents.items[inc_id]["details"] if inc_id else ""
            self.incidents._close(tr.alert_key, t, f"{details} {old}".strip())
        tr.alert_key, tr.alert_t = None, None

    def _on_failure(self, tr: Tracked, t: float) -> None:
        if t < self.active_from or self.model is None:
            return
        alerted = bool(tr.alert and tr.alert.active and tr.alert_t is not None)
        lead = round(t - tr.alert_t, 1) if alerted else None
        self.outcomes.append({"equipment_id": tr.eq.id, "t": t, "alerted": alerted, "lead_min": lead})
        if alerted:
            tr.alert.reset()
            if self.incidents is not None and tr.alert_key:
                inc_id = self.incidents.by_key.get(tr.alert_key)
                old = self.incidents.items[inc_id]["details"] if inc_id else ""
                self.incidents._close(tr.alert_key, t, f"Сбылось: «{tr.mode_text}» через {lead:.0f} мин после "
                                                       f"предупреждения. {old}".strip())
            tr.alert_key, tr.alert_t = None, None
        self.version += 1

    # ── для API ──

    def stats(self) -> dict:
        n = len(self.outcomes)
        hits = [o for o in self.outcomes if o["alerted"]]
        leads = [o["lead_min"] for o in hits if o["lead_min"] is not None]
        return {"failures": n, "predicted": len(hits), "false_alarms": self.false_alarms,
                "mean_lead_min": round(float(np.mean(leads)), 0) if leads else None,
                "from_t": self.active_from}
