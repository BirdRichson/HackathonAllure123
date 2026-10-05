"""Прогноз выпуска за месяц с интервалом.

Метод — бутстреп по сменам: выпуск каждой оставшейся смены берётся случайно из фактических смен
за последние недели (с их простоями, браком и переналадками), так 4000 раз. Получаем распределение
итога месяца: медиану, интервал 10–90% и вероятность выполнить цель 5500.

Метод простой и объяснимый; проверка на синтетической истории — в docs/ML_REPORT.md (доля месяцев,
попавших в интервал 10–90%).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np


def bootstrap_month(mtd: float, history: list[float], remaining: list[tuple[str, float]], target: float,
                    n_sims: int = 4000, seed: int = 0) -> dict[str, Any]:
    """mtd — выпуск с начала месяца; history — выпуск закрытых смен;
    remaining — оставшиеся смены месяца: (дата, доля смены, которая ещё впереди)."""
    rng = np.random.default_rng(seed)
    h = np.asarray(history, dtype=float)
    fr = np.asarray([f for _, f in remaining], dtype=float)
    if len(h) == 0:
        h = np.array([0.0])
    draws = rng.choice(h, size=(n_sims, len(fr))) * fr if len(fr) else np.zeros((n_sims, 0))
    totals = mtd + draws.sum(axis=1)
    p10, p50, p90 = np.percentile(totals, [10, 50, 90])
    left_shifts = float(fr.sum())

    # Накопленный выпуск по дням — для графика с коридором
    days: list[str] = []
    idx_by_day: dict[str, list[int]] = defaultdict(list)
    for i, (d, _) in enumerate(remaining):
        if d not in idx_by_day:
            days.append(d)
        idx_by_day[d].append(i)
    cum = np.full(n_sims, float(mtd))
    band = []
    for d in days:
        cum = cum + draws[:, idx_by_day[d]].sum(axis=1)
        q = np.percentile(cum, [10, 50, 90])
        band.append({"date": d, "p10": round(float(q[0])), "p50": round(float(q[1])), "p90": round(float(q[2]))})

    return {
        "p10": round(float(p10)), "p50": round(float(p50)), "p90": round(float(p90)),
        "prob_target": round(float((totals >= target).mean()), 3),
        "shift_mean": round(float(h.mean()), 1), "shift_std": round(float(h.std()), 1),
        "shifts_left": round(left_shifts, 2),
        "required_per_shift": round((target - mtd) / left_shifts, 1) if left_shifts > 0 else None,
        "band": band,
        "n_sims": n_sims, "history_shifts": int(len(h)),
    }
