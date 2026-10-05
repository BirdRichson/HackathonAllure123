import { useState } from "react";

import { api } from "../api/client";
import { ForecastChart } from "../charts/charts";
import { AiSource, AiTag, AskBox, InsightCard, RiskPanel } from "../components/ai";
import { Empty, MaintenanceBar, Section, StateChip } from "../components/ui";
import { dateTime, ddmm, hours, int, num, pct } from "../format";
import { usePoll } from "../hooks/usePoll";
import { useLive } from "../store/live";
import { useUi } from "../store/ui";

const AREA_NAME: Record<string, string> = { WELD: "Сварка", PAINT: "Окраска", ASSY: "Сборка", QC: "Контроль" };

function MonthCard() {
  const kpiMonth = useLive((s) => s.kpi?.month.output_mtd);
  const { data: f } = usePoll(() => api.planForecast(), [], 8000);
  if (!f) return null;
  const gap = f.p50 - f.target;
  const probColor = f.prob_target >= 0.8 ? "var(--color-ok)" : f.prob_target >= 0.4 ? "var(--color-warn)" : "var(--color-bad)";
  return (
    <div className="rounded-lg bg-panel p-5">
      <Section
        title={
          <span className="flex items-center gap-2">
            Выполним ли месяц? <AiTag title="Прогноз: бутстреп по фактическим сменам" />
          </span>
        }
        aside={`цель — не менее ${int(f.target)} авто`}
      >
        <div className="grid grid-cols-[1fr_1.15fr_1fr] gap-6">
          <div>
            <div className="text-sm text-muted">Выпущено с начала месяца</div>
            <div className="cond text-[40px] leading-tight font-semibold">{int(kpiMonth ?? f.output_mtd)}</div>
            <div className="text-sm text-muted">
              средняя смена {num(f.shift_mean, 1)}, нужно {num(f.required_per_shift ?? 0, 0)}
            </div>
          </div>
          <div>
            <div className="text-sm text-muted">Прогноз на конец месяца</div>
            <div className="cond text-[40px] leading-tight font-semibold" style={{ color: gap >= 0 ? "var(--color-ok)" : "var(--color-bad)" }}>
              {int(f.p50)}
            </div>
            <div className="text-sm text-muted">
              80% интервал {int(f.p10)}–{int(f.p90)}; {gap >= 0 ? `запас ${int(gap)}` : `не хватает ≈${int(-gap)}`}
            </div>
          </div>
          <div>
            <div className="text-sm text-muted">Вероятность выполнить цель</div>
            <div className="cond text-[40px] leading-tight font-semibold" style={{ color: probColor }}>
              {pct(f.prob_target, 0)}
            </div>
            <div className="text-sm text-muted">предел двух смен ≈{int(f.max_theoretical)}</div>
          </div>
        </div>
        <ForecastChart f={f} height={210} />
        <table className="mt-1 w-full text-sm">
          <thead className="text-left text-muted">
            <tr>
              <th className="py-1 font-normal">Модель</th>
              <th className="py-1 text-right font-normal">Выпущено</th>
              <th className="py-1 text-right font-normal">Прогноз</th>
              <th className="py-1 text-right font-normal">План месяца</th>
            </tr>
          </thead>
          <tbody>
            {f.by_model.map((m) => (
              <tr key={m.model} className="border-t border-line">
                <td className="py-1.5">{m.model}</td>
                <td className="py-1.5 text-right">{int(m.mtd)}</td>
                <td className="py-1.5 text-right font-medium" style={{ color: m.forecast < m.plan ? "var(--color-bad)" : undefined }}>
                  {int(m.forecast)}
                </td>
                <td className="py-1.5 text-right text-muted">{int(m.plan)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-2 text-xs text-muted">
          Прогноз: оставшиеся {num(f.shifts_left, 1)} смены 4000 раз заполняются выпуском случайных смен из последних недель — с их простоями и
          браком. План по моделям в данных завода — {int(f.plan_models)}, цель — {int(f.target)}.
        </p>
      </Section>
    </div>
  );
}

function InsightsPanel() {
  const state = useLive((s) => s.insights);
  const [busy, setBusy] = useState(false);
  const refresh = async (force: boolean) => {
    setBusy(true);
    try {
      useLive.setState({ insights: await api.refreshInsights(force) });
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="rounded-lg bg-panel p-5">
      <Section
        title={
          <span className="flex items-center gap-2">
            Выводы ИИ <AiTag />
          </span>
        }
        aside={
          state ? (
            <span className="flex items-center gap-3">
              <AiSource state={state} />
              <button
                type="button"
                disabled={busy}
                onClick={() => void refresh(state.llm_status === "ok")}
                className="rounded border border-line px-2 py-0.5 text-sm text-ink hover:bg-sunk disabled:opacity-50"
                title="Пересчитать и заново спросить LLM"
              >
                {busy ? "Обновляю…" : "Обновить"}
              </button>
            </span>
          ) : undefined
        }
      >
        {!state ? (
          <Empty>ИИ анализирует данные за 30 дней…</Empty>
        ) : (
          <>
            <p className="rounded-md bg-[#f4f1fc] px-3 py-2.5 text-[15px] leading-snug">{state.summary}</p>
            <div className="mt-1 mb-3 text-xs text-muted">
              Период: {ddmm(state.period.from)}–{ddmm(state.period.to)}, {num(state.period.workdays, 0)} рабочих дней. Обновляется после
              каждой смены.
            </div>
            <div className="flex flex-col gap-3">
              {state.items.map((i, n) => (
                <InsightCard key={i.id} i={i} open={n === 0} />
              ))}
            </div>
          </>
        )}
      </Section>
    </div>
  );
}

function MaintenanceList() {
  const equipment = useLive((s) => s.equipment);
  const openArea = useUi((s) => s.openAreaPanel);
  const list = [...equipment].sort((a, b) => a.maintenance.hours_left - b.maintenance.hours_left);
  return (
    <div className="rounded-lg bg-panel p-5">
      <Section title="Ближайшее плановое ТО" aside="по моточасам">
        {list.length === 0 ? (
          <Empty>Нет данных.</Empty>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-left text-muted">
              <tr>
                <th className="pb-2 font-normal">Оборудование</th>
                <th className="pb-2 font-normal">Состояние</th>
                <th className="w-[34%] pb-2 font-normal">Наработка с последнего ТО</th>
                <th className="pb-2 text-right font-normal">Осталось</th>
                <th className="pb-2 text-right font-normal">Ориентировочно</th>
              </tr>
            </thead>
            <tbody>
              {list.map((e) => (
                <tr key={e.id} className="cursor-pointer border-t border-line hover:bg-sunk" onClick={() => openArea(e.area_id, e.id)}>
                  <td className="py-2">
                    <div className="font-medium">{e.name}</div>
                    <div className="text-xs text-muted">{AREA_NAME[e.area_id]}</div>
                  </td>
                  <td className="py-2">
                    <StateChip state={e.state} size="sm" />
                  </td>
                  <td className="py-2 pr-4">
                    <MaintenanceBar progress={e.maintenance.progress} due={e.maintenance.due} />
                    <div className="mt-1 text-xs text-muted">
                      {num(e.maintenance.hours_since, 0)} из {e.maintenance.interval_h} ч
                    </div>
                  </td>
                  <td className="py-2 text-right font-medium">{e.maintenance.due ? "пора" : hours(e.maintenance.hours_left)}</td>
                  <td className="py-2 text-right text-muted">{dateTime(e.maintenance.next_due_ts)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="mt-3 text-sm text-muted">
          Сейчас ТО проводится в начале первой смены и съедает время выпуска. Завод работает с 08:00 до 24:00 — ночное окно
          свободно.
        </p>
      </Section>
    </div>
  );
}

export function ForecastPage() {
  return (
    <div className="scroll-thin grid min-h-0 flex-1 grid-cols-[1.15fr_1fr] gap-4 overflow-y-auto p-4">
      <div className="flex flex-col gap-4">
        <MonthCard />
        <InsightsPanel />
      </div>
      <div className="flex flex-col gap-4">
        <div className="rounded-lg bg-panel p-5">
          <Section
            title={
              <span className="flex items-center gap-2">
                Риск отказа в ближайшие 2 часа <AiTag />
              </span>
            }
            aside="по телеметрии станков"
          >
            <RiskPanel />
          </Section>
        </div>
        <div className="rounded-lg bg-panel p-5">
          <Section
            title={
              <span className="flex items-center gap-2">
                Спросить ИИ <AiTag />
              </span>
            }
            aside="по данным двойника"
          >
            <AskBox />
          </Section>
        </div>
        <MaintenanceList />
      </div>
    </div>
  );
}
