import { useState } from "react";

import { api } from "../api/client";
import { dateTime, hours, int, minutes, num, pct } from "../format";
import { useLive } from "../store/live";
import { useUi } from "../store/ui";
import { SEVERITY } from "../theme/states";
import type { Insight, InsightsState, PredictionItem } from "../types";
import { Empty, SeverityMark } from "./ui";

/** Метка «ИИ» — всё, что посчитал или написал ИИ, помечено одинаково. */
export function AiTag({ title }: { title?: string }) {
  return (
    <span
      className="inline-flex items-center rounded bg-[#efe9fb] px-1.5 py-px text-[11px] font-semibold tracking-wide text-[#5b3fb0]"
      title={title}
    >
      ИИ
    </span>
  );
}

/** Откуда текст выводов: LLM (Groq/Gemini) или офлайн-шаблон. */
export function AiSource({ state }: { state: InsightsState }) {
  if (state.llm_status === "pending") return <span className="text-sm text-muted">LLM формулирует выводы…</span>;
  if (state.llm_status === "ok" && state.llm)
    return (
      <span className="text-sm text-muted" title={`Ответ за ${num(state.llm.latency_ms / 1000, 1)} с`}>
        Текст: {state.llm.label}
        {state.llm.cached ? " (из кэша)" : ""}
      </span>
    );
  const why = state.llm_status === "error" ? `LLM не ответила: ${state.llm_error ?? ""}` : "Ключ Groq или Gemini не задан";
  return (
    <span className="text-sm text-muted" title={why}>
      Офлайн: текст по шаблону, цифры те же
    </span>
  );
}

function EffectChips({ i }: { i: Insight }) {
  const chips: string[] = [];
  if (i.effect.cars_month) chips.push(`до +${int(i.effect.cars_month)} авто/мес`);
  if (i.effect.defects_month) chips.push(`−${int(i.effect.defects_month)} дефектов/мес`);
  if (!chips.length) return null;
  return (
    <div className="flex flex-wrap gap-1.5">
      {chips.map((c) => (
        <span key={c} className="cond rounded-md bg-[#e3f4ea] px-2 py-0.5 text-[15px] font-semibold text-ok">
          {c}
        </span>
      ))}
    </div>
  );
}

export function InsightCard({ i, open: openDefault = false, inArea = false }: { i: Insight; open?: boolean; inArea?: boolean }) {
  const [open, setOpen] = useState(openDefault);
  const openArea = useUi((s) => s.openAreaPanel);
  return (
    <article
      className="rounded-md border border-line bg-panel p-3.5"
      style={{ borderLeft: `4px solid ${SEVERITY[i.severity].color}` }}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <SeverityMark severity={i.severity} />
          {i.area_id && !inArea && (
            <button type="button" onClick={() => openArea(i.area_id!)} className="text-xs text-info hover:underline">
              открыть цех
            </button>
          )}
        </div>
        <EffectChips i={i} />
      </div>
      <h3 className="mt-1.5 text-[16px] leading-snug font-semibold">{i.title}</h3>
      <p className="mt-1 text-[14px] leading-snug text-ink">{i.summary}</p>
      <div className="mt-2 rounded bg-sunk px-2.5 py-1.5 text-[14px] leading-snug">
        <span className="font-semibold">Что сделать: </span>
        {i.recommendation}
      </div>
      <div className="mt-1.5 flex items-center justify-between gap-3 text-sm">
        <span className="text-muted">{i.effect.text}</span>
        <button type="button" onClick={() => setOpen(!open)} className="shrink-0 text-info hover:underline" aria-expanded={open}>
          {open ? "Скрыть" : "Доказательства"}
        </button>
      </div>
      {open && (
        <div className="mt-2 border-t border-line pt-2 text-sm">
          <ul className="list-disc pl-5 text-ink">
            {i.evidence.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
          {i.cost && <p className="mt-1.5 text-muted">Затраты: {i.cost}.</p>}
          {i.assumptions && i.assumptions.length > 0 && (
            <p className="mt-0.5 text-muted">Допущения: {i.assumptions.join("; ")}.</p>
          )}
          <p className="mt-0.5 text-faint">
            Цифры посчитаны по данным двойника; {i.source === "llm" ? "текст написала LLM, числа сверены с расчётом" : "текст — шаблон"}.
          </p>
        </div>
      )}
    </article>
  );
}

// ─────────────────────────────── риски отказов ───────────────────────────────

const LEVEL = {
  high: { label: "высокий", color: "var(--color-bad)" },
  medium: { label: "растёт", color: "var(--color-warn)" },
  low: { label: "низкий", color: "var(--color-ok)" },
} as const;

function RiskValue({ p }: { p: PredictionItem }) {
  if (p.kind === "ml") {
    const r = p.risk ?? 0;
    return (
      <div className="w-[150px]">
        <div className="flex items-baseline justify-between">
          <span className="cond text-xl font-semibold" style={{ color: LEVEL[p.level].color }}>
            {p.risk == null ? "—" : pct(r, r < 0.1 ? 1 : 0)}
          </span>
          <span className="text-xs text-muted">порог {pct(p.threshold ?? 0.7, 0)}</span>
        </div>
        <div className="relative mt-1 h-1.5 rounded-full bg-sunk">
          <div className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${Math.max(2, r * 100)}%`, background: LEVEL[p.level].color }} />
          <div className="absolute -top-0.5 -bottom-0.5 w-0.5 bg-ink" style={{ left: `${(p.threshold ?? 0.7) * 100}%` }} />
        </div>
      </div>
    );
  }
  if (p.kind === "rule")
    return (
      <div className="w-[150px] text-right">
        <span className="cond text-xl font-semibold" style={{ color: LEVEL[p.level].color }}>
          ×{num(p.indicator ?? 1, 1)}
        </span>
        <div className="text-xs text-muted">разброс t°, порог ×{num(p.threshold ?? 2, 0)}</div>
      </div>
    );
  if (p.kind === "filter")
    return (
      <div className="w-[150px] text-right">
        <span className="cond text-xl font-semibold" style={{ color: LEVEL[p.level].color }}>
          {p.dp == null ? "—" : `${int(p.dp)} Па`}
        </span>
        <div className="text-xs text-muted">
          {p.hours_to_limit != null ? `до предела ≈${hours(p.hours_to_limit)} работы` : "перепад стабилен"}
        </div>
      </div>
    );
  return (
    <div className="w-[150px] text-right">
      <span className="cond text-xl font-semibold text-muted">{pct(p.risk ?? 0, 0)}</span>
      <div className="text-xs text-muted">фон, ≈{num(p.per_month ?? 0, 1)} сбоя в мес.</div>
    </div>
  );
}

const KIND_NOTE: Record<PredictionItem["kind"], string> = {
  ml: "LightGBM",
  rule: "правило",
  filter: "тренд",
  base_rate: "по частоте",
};

export function RiskRow({ p, onClick }: { p: PredictionItem; onClick?: () => void }) {
  const showFactors = (p.kind === "ml" || p.kind === "rule") && p.level !== "low" && p.factors && p.factors.length > 0;
  return (
    <li
      className={`grid grid-cols-[1fr_auto] items-center gap-3 py-2 ${onClick ? "cursor-pointer hover:bg-sunk" : ""}`}
      onClick={onClick}
      style={p.alert ? { boxShadow: "inset 3px 0 0 var(--color-bad)" } : undefined}
    >
      <div className="pl-2">
        <div className="flex items-center gap-2">
          <span className="font-medium">{p.name}</span>
          <span className="text-xs text-faint">{KIND_NOTE[p.kind]}</span>
          {p.alert && <AiTag title="Открыто предупреждение" />}
        </div>
        <div className="text-xs text-muted">
          {p.kind === "filter"
            ? p.limit_ts && p.hours_to_limit != null && p.hours_to_limit < 48
              ? `замена фильтра понадобится ≈${dateTime(p.limit_ts)}`
              : "замена фильтра"
            : p.failure.toLowerCase()}
          {p.status !== "ok" && " · сейчас стоит"}
        </div>
        {showFactors && (
          <div className="mt-0.5 text-xs text-ink">{p.factors!.map((f) => `${(f.label.split(",")[0] ?? f.label).toLowerCase()} ${f.value}`).join(", ")}</div>
        )}
      </div>
      <RiskValue p={p} />
    </li>
  );
}

export function RiskPanel({ area }: { area?: string }) {
  const pred = useLive((s) => s.predictions);
  const openArea = useUi((s) => s.openAreaPanel);
  if (!pred) return <Empty>Загружаю прогноз…</Empty>;
  const order = { ml: 0, rule: 1, filter: 2, base_rate: 3 };
  const items = pred.items
    .filter((p) => !area || p.area_id === area)
    .sort((a, b) => order[a.kind] - order[b.kind] || (b.risk ?? b.indicator ?? 0) - (a.risk ?? a.indicator ?? 0));
  const st = pred.stats_30d;
  // На общей странице случайные отказы (роботы, стенды) сворачиваем в строку на тип — они не прогнозируются.
  const shown = area ? items : items.filter((p) => p.kind !== "base_rate");
  const groups = area ? [] : groupBaseRate(items.filter((p) => p.kind === "base_rate"));
  return (
    <div>
      <ul className="flex flex-col divide-y divide-line text-sm">
        {shown.map((p) => (
          <RiskRow key={p.equipment_id} p={p} onClick={area ? undefined : () => openArea(p.area_id, p.equipment_id)} />
        ))}
        {groups.map((g) => (
          <li key={g.type} className="grid grid-cols-[1fr_auto] items-center gap-3 py-2">
            <div className="pl-2">
              <div className="flex items-center gap-2">
                <span className="font-medium">{g.label}</span>
                <span className="text-xs text-faint">по частоте</span>
              </div>
              <div className="text-xs text-muted">
                {g.failure.toLowerCase()}: случайные сбои, предвестника нет — {g.names}
              </div>
            </div>
            <div className="w-[150px] text-right">
              <span className="cond text-xl font-semibold text-muted">{pct(g.risk, 0)}</span>
              <div className="text-xs text-muted">фон на станок</div>
            </div>
          </li>
        ))}
      </ul>
      {!area && (
        <p className="mt-2 text-sm text-muted">
          {pred.model_loaded
            ? st.failures
              ? `За 30 дней ИИ заранее предупредил о ${st.predicted} из ${st.failures} износовых отказов${
                  st.mean_lead_min ? `, в среднем за ${minutes(st.mean_lead_min)}` : ""
                }.`
              : "За 30 дней износовых отказов не было."
            : "Модель прогноза не загружена — выполните make train."}{" "}
          Сбои датчиков роботов случайны: их ИИ не прогнозирует, а показывает фоновую вероятность.
        </p>
      )}
    </div>
  );
}

const TYPE_LABEL: Record<string, string> = { robot: "Роботы ABB", test_stand: "Стенды контроля" };

function groupBaseRate(items: PredictionItem[]) {
  const by = new Map<string, PredictionItem[]>();
  for (const p of items) by.set(p.type, [...(by.get(p.type) ?? []), p]);
  return [...by.entries()].map(([type, list]) => ({
    type,
    label: TYPE_LABEL[type] ?? type,
    failure: list[0]!.failure,
    names: list.map((p) => p.name).join(", "),
    risk: Math.max(...list.map((p) => p.risk ?? 0)),
  }));
}

// ─────────────────────────────── вопрос ИИ ───────────────────────────────

const EXAMPLES = ["Почему окраска даёт брак выше нормы?", "Что сделать, чтобы выполнить план месяца?", "Какой станок сейчас в зоне риска?"];

export function AskBox({ area }: { area?: string }) {
  const ai = useLive((s) => s.ai);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [ans, setAns] = useState<{ text: string; error?: boolean; source?: string; follow?: string[] } | null>(null);
  const ask = async (question: string) => {
    if (question.trim().length < 3) return;
    setQ(question);
    setBusy(true);
    try {
      const r = await api.ask(question, area);
      setAns(r.answer ? { text: r.answer, source: r.source, follow: r.follow_up } : { text: r.error ?? "Нет ответа", error: true });
    } catch (e) {
      setAns({ text: (e as Error).message, error: true });
    } finally {
      setBusy(false);
    }
  };
  return (
    <div>
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void ask(q);
        }}
      >
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Спросите о заводе своими словами"
          className="min-w-0 flex-1 rounded-md border border-line bg-panel px-3 py-2 text-[15px]"
          aria-label="Вопрос ИИ-помощнику"
        />
        <button
          type="submit"
          disabled={busy || q.trim().length < 3}
          className="rounded-md bg-ink px-4 text-sm font-semibold text-white disabled:opacity-40"
        >
          {busy ? "Думаю…" : "Спросить"}
        </button>
      </form>
      {!ans && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {EXAMPLES.map((e) => (
            <button key={e} type="button" onClick={() => void ask(e)} className="rounded-full border border-line px-2.5 py-0.5 text-xs text-muted hover:bg-sunk">
              {e}
            </button>
          ))}
        </div>
      )}
      {ans && (
        <div className={`mt-2 rounded-md px-3 py-2 text-[14px] leading-snug ${ans.error ? "bg-sunk text-muted" : "bg-[#f4f1fc]"}`}>
          {ans.text}
          {ans.source && <div className="mt-1 text-xs text-faint">{ans.source}</div>}
          {ans.follow && ans.follow.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {ans.follow.map((f) => (
                <button key={f} type="button" onClick={() => void ask(f)} className="rounded-full border border-line bg-panel px-2.5 py-0.5 text-xs hover:bg-sunk">
                  {f}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
      {!ai?.llm_online && !ans && (
        <p className="mt-2 text-xs text-muted">Ответы на вопросы работают с бесплатным ключом Groq или Gemini (файл .env).</p>
      )}
    </div>
  );
}
