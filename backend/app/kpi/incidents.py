"""Инциденты и отклонения по целевым показателям завода.

Правила (цели — config/targets.yaml, из данных организаторов):
- авария оборудования — инцидент открыт, пока оборудование стоит;
- брак участка за смену выше 2% (после 30 кузовов) — инцидент на смену;
- незапланированный простой критического оборудования за сутки ≥ 45 мин — предупреждение, > 60 мин — критично;
- OEE участка за закрытую смену ниже 85% — отклонение.
"""

from __future__ import annotations

from typing import Any, Callable

from app.config import plant_config, targets_config
from app.kpi.engine import MAIN_AREAS, area_kpi


def _pct(x: float) -> str:
    s = f"{x * 100:.1f}".replace(".", ",")
    return (s[:-2] if s.endswith(",0") else s) + "%"


class IncidentEngine:
    def __init__(self, sim, iso: Callable[[float], str]) -> None:
        self.sim = sim
        self.iso = iso
        self.t = targets_config()
        plant = plant_config()
        self.eq = {e["id"]: e for e in plant["equipment"]}
        self.area_name = {a["id"]: a["name"] for a in plant["areas"]}
        self.plan_per_shift = float(plant["rates"]["plan_units_per_shift"])
        self.items: dict[str, dict] = {}
        self.by_key: dict[str, str] = {}
        self.changed: list[dict] = []
        self._seq = 0
        self._shift_counts: dict[tuple, list[int]] = {}
        self._down_since: dict[str, tuple[float, str]] = {}
        self._daily_down: dict[tuple[int, str], float] = {}
        sim.rec.listeners.append(self.on_record)
        sim.env.process(self._shift_watch())

    # ── служебное ──

    def _open(self, key: str, t: float, severity: str, kind: str, area_id: str | None, equipment_id: str | None,
              title: str, details: str = "", closed_at: float | None = None) -> dict:
        if key in self.by_key:
            inc = self.items[self.by_key[key]]
            inc.update(title=title, details=details, severity=severity)
        else:
            self._seq += 1
            inc = {"id": f"INC-{self._seq:05d}", "key": key, "ts_start": self.iso(t), "ts_end": None,
                   "status": "open", "severity": severity, "type": kind, "area_id": area_id,
                   "equipment_id": equipment_id, "title": title, "details": details}
            self.items[inc["id"]] = inc
            self.by_key[key] = inc["id"]
        if closed_at is not None:
            inc.update(status="closed", ts_end=self.iso(closed_at))
        self.changed.append(dict(inc))
        return inc

    def _close(self, key: str, t: float, details: str | None = None) -> None:
        iid = self.by_key.get(key)
        if iid and self.items[iid]["status"] == "open":
            inc = self.items[iid]
            inc.update(status="closed", ts_end=self.iso(t))
            if details:
                inc["details"] = details
            self.changed.append(dict(inc))

    def drain(self) -> list[dict]:
        out, self.changed = self.changed, []
        return out

    # ── реакция на события модели ──

    def on_record(self, kind: str, row: Any) -> None:
        if kind == "state" and row[1] == "equipment":
            self._on_equipment(row)
        elif kind == "unit":
            self._on_unit(row)

    def _on_equipment(self, row: tuple) -> None:
        t, _, eq_id, area_id, state, reason, text, planned = row
        eq = self.eq[eq_id]
        if state == "down":
            self._down_since[eq_id] = (t, text)
            self._open(f"down:{eq_id}:{t:.3f}", t, "critical" if eq["critical"] else "warning", "downtime",
                       area_id, eq_id, f"Авария: {eq['name']} — {text}",
                       f"{self.area_name[area_id]}: участок остановлен до устранения.")
        elif state == "running" and eq_id in self._down_since:
            t0, text0 = self._down_since.pop(eq_id)
            dur = t - t0
            self._close(f"down:{eq_id}:{t0:.3f}", t, f"{text0}: простой {dur:.0f} мин.")
            if eq["critical"]:
                day = int(t0 // 1440)
                total = self._daily_down.get((day, eq_id), 0.0) + dur
                self._daily_down[(day, eq_id)] = total
                lim = float(self.t["critical_downtime_max_min_per_day"])
                warn = float(self.t["critical_downtime_warn_min"])
                if total > lim:
                    self._open(f"limit:{day}:{eq_id}", t, "critical", "threshold", area_id, eq_id,
                               f"{eq['name']}: простой за сутки {total:.0f} мин — выше лимита {lim:.0f} мин",
                               "Лимит простоя критического оборудования — 60 минут в сутки.", closed_at=t)
                elif total >= warn:
                    self._open(f"limit:{day}:{eq_id}", t, "warning", "threshold", area_id, eq_id,
                               f"{eq['name']}: простой за сутки {total:.0f} мин — {total / lim * 100:.0f}% лимита",
                               "Лимит простоя критического оборудования — 60 минут в сутки.", closed_at=t)

    def _on_unit(self, row: tuple) -> None:
        t, _, _, area_id, defect = row
        if area_id not in MAIN_AREAS:
            return
        s = self.sim.cal.shift_at(t - 1e-9)
        if s is None:
            return
        key = (s[0], s[1], area_id)
        c = self._shift_counts.setdefault(key, [0, 0])
        c[0] += 1
        c[1] += defect != ""
        produced, defects = c
        if produced < 40 or defects < 3:   # на первых кузовах и единичном браке доля ещё ничего не значит
            return
        rate = defects / produced
        dmax = float(self.t["defect_rate_max"])
        ikey = f"quality:{s[0]}:{s[1]}:{area_id}"
        iid = self.by_key.get(ikey)
        is_new = iid is None and rate > dmax
        is_update = iid is not None and self.items[iid]["status"] == "open" and defect != ""
        if is_new or is_update:
            self._open(ikey, t, "critical" if rate > 2 * dmax else "warning", "quality", area_id, None,
                       f"{self.area_name[area_id]}: брак {_pct(rate)} при норме {_pct(dmax)}",
                       f"Смена {s[1]}: {defects} из {produced} кузовов с дефектами.")

    def _shift_watch(self):
        """В конце каждой смены — OEE участков против цели и закрытие инцидентов по браку."""
        cal = self.sim.cal
        env = self.sim.env
        while True:
            now = env.now
            if cal.in_shift(now):
                end = cal.shift_end(now)
            else:
                start = cal.next_shift_start(now)
                end = cal.shift_end(start)
            s = cal.shift_at(end - 1e-6)
            yield env.timeout(end - now)
            if s is None:
                continue
            start = end - 60 * float(plant_config()["schedule"]["shift_hours"])
            for area_id in MAIN_AREAS:
                k = area_kpi(self.sim, area_id, start, end, end - start, self.plan_per_shift)
                if k["oee"] < self.t["oee_min"]:
                    sev = "warning" if k["oee"] >= self.t["oee_red_below"] else "critical"
                    self._open(f"oee:{s[0]}:{s[1]}:{area_id}", end, sev, "oee", area_id, None,
                               f"{self.area_name[area_id]}: OEE за смену {_pct(k['oee'])} — ниже цели "
                               f"{_pct(self.t['oee_min'])}",
                               f"Доступность {_pct(k['availability'])}, производительность "
                               f"{_pct(k['performance'])}, качество {_pct(k['quality'])}; "
                               f"выпуск {k['fact_units']} при плане {self.plan_per_shift:.0f}.", closed_at=end)
                self._close(f"quality:{s[0]}:{s[1]}:{area_id}", end)
