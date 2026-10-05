"""ИИ-помощник двойника: одна точка входа для API и живого потока.

- риск отказов по оборудованию (LightGBM, тренд фильтров, частота случайных сбоев);
- прогноз выпуска за месяц с интервалом;
- выводы ИИ: факты и эффект считает код, текст пишет LLM (Groq/Gemini) или шаблон без сети;
- разбор отчётов рабочих и подсказка причины для формы;
- ответы на вопросы о заводе (только с LLM).
"""

from __future__ import annotations

import asyncio
import json
import time
from bisect import bisect_left
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import numpy as np

from app.assistant import insights as ins
from app.assistant.llm import LLMError, get_client
from app.assistant.reports import (accuracy_vs_truth, ai_fields, analysis, is_mismatch, llm_classify,
                                   reason_label)
from app.config import plant_config, targets_config
from app.ml.failure import HORIZON_MIN, FailureModel
from app.ml.forecast import bootstrap_month
from app.ml.report_classifier import SUBTYPE_LABEL, classify, report_text
from app.sim.engine import DAY_MIN

if TYPE_CHECKING:
    from app.runtime import Runtime

_MODEL: FailureModel | None = None
_MODEL_LOADED = False


def failure_model() -> FailureModel | None:
    """Модель прогноза отказов с диска (data/models). Загружается один раз."""
    global _MODEL, _MODEL_LOADED
    if not _MODEL_LOADED:
        _MODEL = FailureModel.load()
        _MODEL_LOADED = True
    return _MODEL


SHIFT_MIN = 480.0


class AIService:
    def __init__(self, rt: "Runtime") -> None:
        self.rt = rt
        self.llm = get_client()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.state: dict | None = None
        self._key: float | None = None
        self._facts: dict | None = None
        self._task: asyncio.Task | None = None
        self._pred_sent = (-1, -1.0)
        self._base_rates: tuple[float, dict] | None = None
        self.version = 0

    # ─────────────────────────── служебное ───────────────────────────

    @property
    def world(self):
        return self.rt.world

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def on_reset(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        self.state, self._key, self._facts, self._base_rates = None, None, None, None
        self._pred_sent = (-1, -1.0)

    def brief(self) -> dict:
        st = self.llm.status()
        active = next((p for p in st["providers"] if p["configured"] and not p["disabled_reason"]), None)
        return {"llm_online": st["online"], "llm_label": (f"{active['label']} · {active['models'][0]}" if active else None),
                "failure_model": failure_model() is not None}

    def status(self) -> dict:
        m = failure_model()
        reps = self.rt.db.list_reports(limit=5000, include_truth=True)
        from app.ml.report_classifier import get_classifier  # noqa: F401  (модель уже загружена при разметке)

        return {
            "llm": self.llm.status(),
            "failure_model": None if m is None else {
                "trained_at": m.meta.get("trained_at"), "horizon_min": m.meta.get("horizon_min"),
                "alert": m.meta.get("alert"), "metrics": {k: m.meta["metrics"].get(k) for k in
                                                          ("test", "by_type", "live_replay", "forecast", "reports")},
            },
            "report_classifier": {"kind": "TF-IDF + логистическая регрессия", "offline": True,
                                  "check_on_simulator_truth": accuracy_vs_truth(reps)},
            "insights": None if self.state is None else {k: self.state.get(k) for k in
                                                          ("generated_at", "llm_status", "llm", "llm_error")},
        }

    # ─────────────────────────── прогноз отказов ───────────────────────────

    def _rates(self) -> dict:
        """Фоновая вероятность случайных отказов по типам — по частоте за 30 дней (кэш на смену)."""
        sim = self.world.sim
        key = ins.period_end(sim)
        if self._base_rates and self._base_rates[0] == key:
            return self._base_rates[1]
        from app.views import stop_intervals

        t0 = max(0.0, key - 30 * DAY_MIN)
        hours = len(sim.cal.shift_windows(t0, key)) * SHIFT_MIN / 60
        by_type: dict[str, dict] = {}
        for eq in sim.equipment.values():
            d = by_type.setdefault(eq.type, {"n_eq": 0, "failures": 0})
            d["n_eq"] += 1
        for s in stop_intervals(sim, t0, key):
            if s["kind"] == "equipment" and s["equipment_id"]:
                by_type[sim.equipment[s["equipment_id"]].type]["failures"] += 1
        for d in by_type.values():
            rate = d["failures"] / max(hours * d["n_eq"], 1.0)     # отказов на станок в час работы
            d["p_horizon"] = 1 - float(np.exp(-rate * HORIZON_MIN / 60))
            d["per_month"] = d["failures"] / d["n_eq"] * (22 / max(hours / 16, 1))
        self._base_rates = (key, by_type)
        return by_type

    def _filter_forecast(self, eq) -> dict:
        """Перепад на фильтре камеры: тренд за последние часы работы и сколько осталось до порогов."""
        from app.views import _estimate_due

        w = self.world
        f = eq.tcfg["filter"]
        rows = [r for r in list(w.sim.rec.telemetry)[-(len(w.sim.equipment) * 600):] if r[1] == eq.id]
        rows = rows[-480:]
        last = w.sim.rec.last_telemetry.get(eq.id)
        dp = float(last[6]) if last and last[6] is not None else None
        out = {"kind": "filter", "dp": None if dp is None else round(dp), "swap_pa": ins.FILTER_SWAP_PA,
               "limit_pa": f["dp_limit_pa"], "rate_pa_h": None, "hours_to_swap": None, "hours_to_limit": None,
               "limit_ts": None}
        if dp is None or len(rows) < 60:
            return out
        y = np.array([r[6] for r in rows], dtype=float)
        x = np.arange(len(y), dtype=float)
        slope = float(np.polyfit(x, y, 1)[0]) * 60          # Па за час работы
        dp_s = float(np.mean(y[-15:]))
        out["dp"] = round(dp_s)
        if slope > 0.3:
            out["rate_pa_h"] = round(slope, 1)
            h_lim = max(0.0, (f["dp_limit_pa"] - dp_s) / slope)
            out["hours_to_limit"] = round(h_lim, 1)
            out["hours_to_swap"] = round(max(0.0, (ins.FILTER_SWAP_PA - dp_s) / slope), 1)
            due = _estimate_due(w.sim, h_lim)
            out["limit_ts"] = w.iso(due)
        return out

    def predictions(self) -> dict:
        w = self.world
        sim = w.sim
        m = failure_model()
        mon = w.monitor
        rates = self._rates()
        items = []
        for e in plant_config()["equipment"]:
            eq = sim.equipment[e["id"]]
            item = {"equipment_id": eq.id, "name": eq.name, "area_id": eq.area_id, "type": eq.type,
                    "status": eq.status}
            tr = mon.tracked.get(eq.id) if mon else None
            if tr is not None and m is not None:
                a = m.cfg(eq.type)
                score = tr.risk
                active = bool(tr.alert and tr.alert.active)
                level = "high" if active or (score or 0) >= a["thr_on"] else \
                    "medium" if (score or 0) >= a["thr_off"] else "low"
                common = dict(level=level, alert=active, threshold=a["thr_on"], risk_ts=w.iso(tr.risk_t),
                              failure=tr.mode_text)
                if a.get("method") == "rule":
                    item.update(kind="rule", risk=None, indicator=None if score is None else round(score, 2),
                                indicator_label="Разброс температуры к норме",
                                factors=m.factors(tr.x, eq_type=eq.type) if tr.x is not None and level != "low" else [],
                                note="Правило: разброс температуры вдвое выше нормы — признак сбоя горелки",
                                **common)
                else:
                    item.update(kind="ml", risk=None if score is None else round(score, 3),
                                factors=m.factors(tr.x) if (tr.x is not None and (score or 0) >= 0.05) else [],
                                note="Модель LightGBM по току, вибрации и наработке", **common)
            elif eq.tcfg.get("filter"):
                ff = self._filter_forecast(eq)
                h = ff["hours_to_limit"]
                item.update(ff, level="high" if h is not None and h < 4 else "medium" if (ff["dp"] or 0) >= ins.FILTER_SWAP_PA
                            else "low", failure="Замена фильтра",
                            note="Тренд перепада давления на фильтре")
            else:
                r = rates.get(eq.type, {})
                item.update(kind="base_rate", risk=round(r.get("p_horizon", 0.0), 3), level="low",
                            failure=(eq.tcfg.get("failure_modes") or [{}])[0].get("reason_text", "отказ"),
                            per_month=round(r.get("per_month", 0.0), 1),
                            note="Сбои случайные, предвестника нет — вероятность по частоте за 30 дней")
            items.append(item)
        t0 = max(0.0, sim.now - 30 * DAY_MIN)
        outs = [o for o in (mon.outcomes if mon else []) if o["t"] >= t0]
        hits = [o for o in outs if o["alerted"]]
        return {
            "horizon_min": HORIZON_MIN, "updated": w.iso(sim.now), "model_loaded": m is not None,
            "items": items,
            "stats_30d": {"failures": len(outs), "predicted": len(hits),
                          "mean_lead_min": round(float(np.mean([o["lead_min"] for o in hits]))) if hits else None},
        }

    # ─────────────────────────── прогноз месяца ───────────────────────────

    def plan_forecast(self, at: float | None = None) -> dict:
        from app.views import finished_units

        w = self.world
        sim = w.sim
        cal = sim.cal
        plant = plant_config()
        t = sim.now if at is None else at
        now_dt = cal.dt(t)
        month_start = now_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
        t_m0 = (month_start - cal.start).total_seconds() / 60
        t_m1 = (next_month - cal.start).total_seconds() / 60
        mtd = finished_units(sim, max(0.0, t_m0), t)
        month_windows = cal.shift_windows(t_m0, t_m1)
        past = [x for x in cal.shift_windows(max(0.0, t - 40 * DAY_MIN), t) if x[3] <= t]
        hist = [finished_units(sim, a, b) for _, _, a, b in past[-40:]]
        remaining = [(cal.dt(a).date().isoformat(), (b - max(a, t)) / (b - a)) for _, _, a, b in month_windows if b > t]
        target = float(targets_config()["monthly_output_min"])
        res = bootstrap_month(mtd, hist, remaining, target, seed=0)

        # по моделям: факт с начала месяца и доля в недавнем выпуске
        units = sim.rec.units
        i0, i1 = bisect_left(units, (max(0.0, t_m0),)), bisect_left(units, (t,))
        mtd_model: dict[str, int] = {}
        for u in units[i0:i1]:
            if u[3] == "QC":
                mtd_model[u[2]] = mtd_model.get(u[2], 0) + 1
        recent_t0 = past[-10][2] if len(past) >= 10 else 0.0
        j0 = bisect_left(units, (recent_t0,))
        recent: dict[str, int] = {}
        for u in units[j0:i1]:
            if u[3] == "QC":
                recent[u[2]] = recent.get(u[2], 0) + 1
        tot_recent = sum(recent.values()) or 1
        left = res["p50"] - mtd
        by_model = []
        for mdl in plant["models"]:
            share = recent.get(mdl["name"], 0) / tot_recent
            fact = mtd_model.get(mdl["name"], 0)
            by_model.append({"model": mdl["name"], "plan": mdl["plan_month_units"], "mtd": fact,
                             "forecast": round(fact + left * share), "share": round(share, 3)})

        # фактический накопленный выпуск по дням
        actual = []
        cum = 0
        for d in range(int((t - max(0.0, t_m0)) // DAY_MIN) + 1):
            a = max(0.0, t_m0) + d * DAY_MIN
            b = min(a + DAY_MIN, t)
            if b <= a:
                break
            cum += finished_units(sim, a, b)
            actual.append({"date": cal.dt(a).date().isoformat(), "cum": cum})
        ideal = float(plant["rates"]["ideal_cycle_min"])
        return {
            **res, "as_of": w.iso(t), "month": month_start.strftime("%Y-%m"), "target": int(target),
            "plan_models": sum(m["plan_month_units"] for m in plant["models"]), "output_mtd": mtd,
            "shifts_total": len(month_windows), "max_theoretical": round(len(month_windows) * SHIFT_MIN / ideal),
            "by_model": by_model, "actual": actual,
            "partial_history": t_m0 < 0,
        }

    # ─────────────────────────── выводы ───────────────────────────

    def insights(self) -> dict:
        if self.state is None:
            self._recompute()
        return self.state

    def _recompute(self) -> bool:
        """Факты и выводы по правилам за период до конца последней закрытой смены. True — если период сменился."""
        sim = self.world.sim
        key = ins.period_end(sim)
        if self.state is not None and key == self._key:
            return False
        fc = self.plan_forecast(at=key)
        facts = ins.build_facts(self.rt, fc)
        items = ins.rule_insights(facts)
        self._facts, self._key = facts, key
        self.state = {
            "generated_at": self.world.iso(sim.now), "period": facts["period"],
            "summary": ins.template_summary(items, facts), "summary_source": "rules",
            "items": items, "llm": None,
            "llm_status": "pending" if self.llm.available else "offline", "llm_error": None,
            "reports": facts["reports"], "loss_by_area": facts["loss_by_area"],
        }
        self.version += 1
        return True

    async def _llm_pass(self, use_cache: bool = True) -> None:
        state, facts = self.state, self._facts
        if state is None or facts is None:
            return
        rules_items = [dict(i, source="rules") for i in state["items"]]
        try:
            summary, items, meta = await asyncio.to_thread(ins.llm_rewrite, self.llm, rules_items, facts, None, use_cache)
        except LLMError as e:
            if self.state is state:
                state.update(llm_status="offline" if not self.llm.available else "error", llm_error=str(e)[:300])
                self.version += 1
                await self._broadcast_insights()
            return
        if self.state is not state:          # пока ждали ответ, период сменился или был сброс
            return
        state.update(items=items, llm=meta, llm_status="ok", llm_error=None)
        if summary:
            state.update(summary=summary, summary_source="llm")
        self.version += 1
        await self._broadcast_insights()

    def _start_llm(self, use_cache: bool = True) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = asyncio.create_task(self._llm_pass(use_cache))

    async def refresh(self, force: bool = False) -> dict:
        """Пересчитать выводы. force — заново спросить LLM, не беря ответ из кэша."""
        changed = self._recompute()
        if force:
            self.state = None
            self._recompute()
        if self.llm.available or self._cache_possible():
            if changed or force or self.state["llm_status"] in ("pending", "error"):
                self.state["llm_status"] = "pending"
                self._start_llm(use_cache=not force)
                try:
                    await asyncio.wait_for(asyncio.shield(self._task), timeout=40)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass
        return self.state

    def _cache_possible(self) -> bool:
        return self.llm.mode != "off" and self.llm.cache_dir.is_dir()

    async def on_publish(self) -> None:
        """Вызывается рантаймом каждый тик: новый период → новые выводы; изменились риски → рассылка."""
        if self._recompute():
            if self.llm.available or self._cache_possible():
                self.state["llm_status"] = "pending"
                self._start_llm()
            await self._broadcast_insights()
        mon = self.world.monitor
        now = time.monotonic()
        if mon is not None and self.rt.clients and mon.version != self._pred_sent[0] and now - self._pred_sent[1] >= 2.0:
            self._pred_sent = (mon.version, now)
            await self.rt.broadcast({"type": "predictions", "payload": self.predictions()})

    async def _broadcast_insights(self) -> None:
        if self.rt.clients and self.state is not None:
            await self.rt.broadcast({"type": "insights", "payload": self.state})

    # ─────────────────────────── отчёты рабочих ───────────────────────────

    def suggest(self, equipment_id: str, description: str, actions: str = "", reason: str | None = None) -> dict:
        """Подсказка причины по тексту, пока рабочий заполняет форму (локальная модель, мгновенно)."""
        pred = classify(report_text(description, actions))
        if pred is None:
            return {"prediction": None, "mismatch": False}
        return {"prediction": pred.as_dict() | {"reason_label": reason_label(pred.reason)},
                "mismatch": is_mismatch(reason, pred)}

    async def suggest_llm(self, equipment_id: str, description: str, actions: str = "", reason: str | None = None,
                          machine_reason_text: str = "") -> dict:
        report = {"equipment_id": equipment_id, "description": description, "actions_taken": actions,
                  "reason": reason, "machine_reason_text": machine_reason_text}
        try:
            pred = await asyncio.to_thread(llm_classify, self.llm, report)
        except LLMError as e:
            res = self.suggest(equipment_id, description, actions, reason)
            return {**res, "llm_error": str(e)[:300]}
        return {"prediction": pred.as_dict() | {"reason_label": reason_label(pred.reason)},
                "mismatch": is_mismatch(reason, pred), "llm": self.llm.last.__dict__ if self.llm.last else None}

    def schedule_report_llm(self, rid: str) -> None:
        """После отправки формы: разобрать текст LLM в фоне и обновить запись (если есть ключ)."""
        if not self.llm.available or self.loop is None:
            return
        self.loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self._annotate_llm(rid)))

    async def _annotate_llm(self, rid: str) -> None:
        rep = self.rt.db.get_report(rid)
        if not rep or not (rep.get("description") or "").strip():
            return
        try:
            pred = await asyncio.to_thread(llm_classify, self.llm, rep)
        except LLMError:
            return
        self.rt.db.update_report(rid, ai_fields(rep, pred))
        self.world.out.reports[rid] = self.rt.db.get_report(rid)

    def reports_analysis(self, days: float = 30, area: str | None = None) -> dict:
        w = self.world
        t0 = w.iso(max(0.0, w.sim.now - days * DAY_MIN))
        reps = [r for r in self.rt.db.list_reports(area=area, limit=5000) if (r["ts_start"] or "") >= t0]
        names = {e["id"]: e["name"] for e in plant_config()["equipment"]}
        return {"days": days, **analysis(reps, names)}

    # ─────────────────────────── вопросы ───────────────────────────

    async def ask(self, question: str, area_id: str | None = None) -> dict:
        from app import views

        if not self.llm.available:
            return {"answer": None, "error": "Ответы на вопросы работают с LLM: добавьте GROQ_API_KEY или "
                                              "GEMINI_API_KEY в файл .env и перезапустите сервер."}
        rt = self.rt
        k = views.kpi_now(rt)
        ins_state = self.insights()
        pred = self.predictions()
        par = views.pareto(rt, area_id, days=30)
        names = {e["id"]: e["name"] for e in plant_config()["equipment"]}
        ctx = {
            "сейчас": k["sim_time"],
            "смена": {"OEE завода": k["shift"]["plant"]["oee"], "выпуск": k["shift"]["output"],
                      "по участкам": {a: {"OEE": v["oee"], "брак": v["defect_rate"]} for a, v in k["shift"]["areas"].items()}},
            "месяц": {kk: v for kk, v in self.plan_forecast().items() if kk in
                      ("output_mtd", "p10", "p50", "p90", "prob_target", "target", "required_per_shift", "shift_mean")},
            "участки": {a["name"]: a["reason_text"] or a["state"] for a in views.areas_brief(rt)},
            "открытые инциденты": [i["title"] for i in rt.db.list_incidents(status="open", limit=10)],
            "выводы ИИ": [{"заголовок": i["title"], "эффект": i["effect"]["text"]} for i in ins_state["items"]],
            "риски отказов": [{"станок": p["name"], "риск": p.get("risk"), "уровень": p["level"]}
                              for p in pred["items"] if p.get("kind") == "ml" or p["level"] != "low"],
            "причины простоев за 30 дней (мин)": {r["reason_text"]: r["minutes"] for r in par["reasons"][:8]},
            "последние отчёты рабочих": [{"станок": names.get(r["equipment_id"]), "причина": reason_label(r["reason"]),
                                          "текст": r["description"]} for r in rt.db.list_reports(area=area_id, limit=6)],
            "цели": targets_config(),
        }
        system = (
            "Ты — ИИ-помощник начальника производства автозавода АЛЛЮР в цифровом двойнике. Отвечай по-русски, "
            "коротко (до 5 предложений), простыми словами, только по данным из контекста. Если данных не хватает — "
            "так и скажи. Доли (0.87) называй процентами (87%). Ночью 00:00–08:00 завод не работает. "
            'Ответ — JSON: {"answer": "...", "follow_up": ["уточняющий вопрос", "..."]}'
        )
        user = f"Контекст (JSON): {json.dumps(ctx, ensure_ascii=False)}\n\nВопрос: {question.strip()}"
        try:
            res = await asyncio.to_thread(self.llm.complete_json, "ask", system, user, max_tokens=700)
        except LLMError as e:
            return {"answer": None, "error": f"LLM недоступна: {str(e)[:200]}"}
        fu = res.data.get("follow_up") or []
        return {"answer": str(res.data.get("answer") or "").strip(), "follow_up": [str(x) for x in fu][:3],
                "source": res.label, "cached": res.cached}


__all__ = ["AIService", "failure_model", "SUBTYPE_LABEL"]
