"""Связь качества окраски с состоянием фильтров камер.

Для каждого окрашенного кузова запоминаем перепад давления на фильтрах в момент окраски
(максимум по двум камерам — кузов проходит обе) и был ли дефект. Из этого ИИ-вывод считает,
насколько брак выше при засорённых фильтрах и сколько дефектов можно убрать заменой по состоянию.
"""

from __future__ import annotations

from bisect import bisect_left
from typing import Any

BINS = [(0, 250, "до 250 Па"), (250, 300, "250–300 Па"), (300, 350, "300–350 Па"), (350, 400, "350–400 Па"),
        (400, 10_000, "400 Па и выше")]


class PaintQualityTracker:
    def __init__(self, sim, area_id: str = "PAINT") -> None:
        self.sim = sim
        self.area_id = area_id
        self.booths = [e.id for e in sim.areas[area_id].equipment if e.tcfg.get("filter")]
        self.rows: list[tuple[float, float, bool, bool]] = []   # (t, перепад, дефект, сорность)
        sim.rec.listeners.append(self.on_record)

    def on_record(self, kind: str, row: Any) -> None:
        if kind != "unit" or row[3] != self.area_id:
            return
        last = self.sim.rec.last_telemetry
        dps = [last[b][6] for b in self.booths if b in last and last[b][6] is not None]
        if not dps:
            return
        defect = row[4]
        self.rows.append((row[0], max(dps), defect != "", defect == "PAINT_DIRT"))

    def stats(self, t0: float, t1: float, split_pa: float) -> dict:
        i, j = bisect_left(self.rows, (t0,)), bisect_left(self.rows, (t1,))
        rows = self.rows[i:j]
        bins = []
        for lo, hi, label in BINS:
            sel = [r for r in rows if lo <= r[1] < hi]
            n = len(sel)
            d = sum(r[2] for r in sel)
            bins.append({"label": label, "from_pa": lo, "units": n, "defects": d,
                         "dirt": sum(r[3] for r in sel), "rate": d / n if n else None})
        lo_rows = [r for r in rows if r[1] < split_pa]
        hi_rows = [r for r in rows if r[1] >= split_pa]
        rate_lo = sum(r[2] for r in lo_rows) / len(lo_rows) if lo_rows else 0.0
        rate_hi = sum(r[2] for r in hi_rows) / len(hi_rows) if hi_rows else 0.0
        return {"units": len(rows), "defects": sum(r[2] for r in rows), "bins": bins,
                "units_hi": len(hi_rows), "defects_hi": sum(r[2] for r in hi_rows),
                "rate_lo": rate_lo, "rate_hi": rate_hi,
                "excess_defects": max(0.0, len(hi_rows) * (rate_hi - rate_lo))}
