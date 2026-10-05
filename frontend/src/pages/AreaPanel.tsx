import { useEffect } from "react";

import { api } from "../api/client";
import { ParetoChart, ShiftHistoryChart, TelemetryChart } from "../charts/charts";
import { Empty, MaintenanceBar, Section, SeverityMark, StateChip, TargetBar } from "../components/ui";
import { dateTime, hhmm, hours, int, minutes, num, pct } from "../format";
import { usePoll } from "../hooks/usePoll";
import { useLive } from "../store/live";
import { useUi } from "../store/ui";
import { LEVEL_COLOR } from "../theme/states";
import type { AreaView, EquipmentBrief, Kpi, Targets } from "../types";
import { useEquipmentName } from "./PlantPage";

function KpiTile({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div className="min-w-[120px]">
      <div className="text-sm text-muted">{label}</div>
      <div className="cond text-[30px] leading-tight font-semibold" style={{ color }}>
        {value}
      </div>
      {sub && <div className="text-xs text-muted">{sub}</div>}
    </div>
  );
}

function Header({ view, onClose }: { view: AreaView; onClose: () => void }) {
  const simTime = useLive((s) => s.status?.sim_time ?? null);
  const k = view.kpi.shift;
  const t = view.targets;
  return (
    <div className="flex items-start gap-8 border-b border-line px-6 py-4">
      <div className="min-w-[230px]">
        <div className="flex items-baseline gap-3">
          <h1 className="cond text-[34px] leading-none font-semibold">{view.area.name}</h1>
          {view.area.line_id && <span className="text-muted">линия {view.area.line_id}</span>}
        </div>
        <div className="mt-2 flex items-center gap-2">
          <StateChip state={view.area.state} />
          {view.area.state !== "running" && view.area.reason_text && (
            <span className="text-sm text-muted">{view.area.reason_text}</span>
          )}
        </div>
      </div>
      {k && (
        <div className="flex flex-1 gap-8">
          <KpiTile label="OEE смены" value={pct(k.oee)} sub={`цель ${pct(t.oee_min, 0)}`} color={LEVEL_COLOR[k.level]} />
          {view.area.id !== "QC" && (
            <KpiTile
              label="Брак смены"
              value={pct(k.defect_rate)}
              sub={`${int(k.defects)} из ${int(k.fact_units)}, норма ${pct(t.defect_rate_max, 0)}`}
              color={k.defect_rate > t.defect_rate_max ? "var(--color-bad)" : "var(--color-ok)"}
            />
          )}
          <KpiTile label="Выпуск за смену" value={`${int(k.fact_units)}`} sub={`план к ${hhmm(simTime)}: ${int(k.plan_units)}`} />
          <KpiTile label="Доступность" value={pct(k.availability)} sub={`работа ${minutes(k.run_min)} из ${minutes(k.planned_min)}`} />
        </div>
      )}
      <button
        type="button"
        onClick={onClose}
        className="rounded-md border border-line px-3 py-1.5 text-sm hover:bg-sunk"
        aria-label="Закрыть страницу цеха"
      >
        Закрыть
      </button>
    </div>
  );
}

function telemetryLine(e: EquipmentBrief): string {
  const t = e.telemetry;
  if (!t) return "нет данных";
  if (t.filter_dp != null) return `перепад на фильтре ${num(t.filter_dp)} Па`;
  return `ток ${num(t.current, 1)} А, вибрация ${num(t.vibration, 1)} мм/с`;
}

function EquipmentRow({
  e,
  selected,
  onSelect,
  onReport,
}: {
  e: EquipmentBrief;
  selected: boolean;
  onSelect: () => void;
  onReport: () => void;
}) {
  const m = e.maintenance;
  return (
    <li
      className={`grid cursor-pointer grid-cols-[1.1fr_1.4fr_1fr] items-center gap-4 rounded-md border px-3 py-2.5 ${
        selected ? "border-ink bg-sunk" : "border-line hover:bg-sunk"
      }`}
      onClick={onSelect}
    >
      <div>
        <div className="font-semibold">{e.name}</div>
        <div className="mt-1 flex items-center gap-2">
          <StateChip state={e.state} size="sm" />
          {e.source === "data" && (
            <span className="text-xs text-muted" title="Это оборудование упомянуто в данных завода">
              из данных
            </span>
          )}
        </div>
      </div>
      <div>
        <div className="flex items-baseline justify-between text-sm">
          <span className="text-muted">До планового ТО</span>
          <span className="font-medium" style={{ color: m.due || m.progress >= 0.95 ? "var(--color-bad)" : undefined }}>
            {m.due ? "пора сейчас" : `${hours(m.hours_left)} работы`}
          </span>
        </div>
        <div className="mt-1.5">
          <MaintenanceBar progress={m.progress} due={m.due} />
        </div>
        <div className="mt-1 text-xs text-muted">
          интервал {m.interval_h} ч, ориентировочно {dateTime(m.next_due_ts)}
        </div>
      </div>
      <div className="text-sm">
        <div className="text-muted">{telemetryLine(e)}</div>
        {e.state === "down" && (
          <button
            type="button"
            onClick={(ev) => {
              ev.stopPropagation();
              onReport();
            }}
            className="mt-1 rounded border border-bad px-2 py-0.5 text-xs font-medium text-bad hover:bg-[#fbe2df]"
          >
            Заполнить отчёт о простое
          </button>
        )}
      </div>
    </li>
  );
}

function KpiNote({ k, t }: { k: Kpi | null; t: Targets }) {
  if (!k) return null;
  return (
    <div className="grid grid-cols-2 gap-4 text-sm">
      <div>
        <div className="mb-1 flex justify-between">
          <span className="text-muted">OEE за сутки</span>
          <b>{pct(k.oee)}</b>
        </div>
        <TargetBar value={k.oee} target={t.oee_min} />
      </div>
      <div>
        <div className="mb-1 flex justify-between">
          <span className="text-muted">Брак за сутки</span>
          <b>{pct(k.defect_rate)}</b>
        </div>
        <TargetBar value={k.defect_rate} target={t.defect_rate_max} max={0.08} invert />
      </div>
    </div>
  );
}

export function AreaPanel() {
  const { openArea, closeArea, selectedEq, selectEq, startReport } = useUi();
  const journalSeq = useLive((s) => s.journalSeq);
  const name = useEquipmentName();

  const { data: view } = usePoll(() => (openArea ? api.area(openArea) : Promise.resolve(null)), [openArea, journalSeq], 4000);
  const eqId = selectedEq ?? view?.equipment[0]?.id ?? null;
  const { data: eq } = usePoll(() => (eqId ? api.equipment(eqId) : Promise.resolve(null)), [eqId], 5000);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && closeArea();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [closeArea]);

  if (!openArea) return null;
  const ready = view && view.area.id === openArea;
  const stops = view?.pareto.reasons.filter((r) => r.kind !== "flow") ?? [];
  const waiting = view?.pareto.reasons.filter((r) => r.kind === "flow").reduce((a, r) => a + r.minutes, 0) ?? 0;

  return (
    <div className="fixed inset-x-0 top-16 bottom-0 z-40 flex justify-end">
      <div className="absolute inset-0 bg-[#1c2630]/25" onClick={closeArea} aria-hidden />
      <div
        className="slide-in relative flex h-full w-[min(1240px,92vw)] flex-col bg-ground shadow-2xl"
        role="dialog"
        aria-label="Страница цеха"
      >
        {!ready ? (
          <div className="p-8 text-muted">Загружаю цех…</div>
        ) : (
          <>
            <div className="bg-panel">
              <Header view={view} onClose={closeArea} />
            </div>
            <div className="scroll-thin grid flex-1 grid-cols-[1.25fr_1fr] gap-4 overflow-y-auto p-4">
              <div className="flex flex-col gap-4">
                <div className="rounded-lg bg-panel p-4">
                  <Section title="Оборудование" aside="нажмите, чтобы увидеть датчики">
                    <ul className="flex flex-col gap-2">
                      {view.equipment.map((e) => (
                        <EquipmentRow
                          key={e.id}
                          e={e}
                          selected={e.id === eqId}
                          onSelect={() => selectEq(e.id)}
                          onReport={() => startReport(e.id)}
                        />
                      ))}
                    </ul>
                  </Section>
                </div>
                <div className="rounded-lg bg-panel p-4">
                  <Section title={eq ? `Датчики: ${eq.name}` : "Датчики"} aside="последние 8 часов">
                    {eq && eq.telemetry_series.ts.length > 1 ? (
                      <TelemetryChart eq={eq} />
                    ) : (
                      <Empty>Данных за смену пока нет.</Empty>
                    )}
                    {eq && eq.stops.length > 0 && (
                      <div className="mt-2 text-sm text-muted">
                        Последние остановки:{" "}
                        {eq.stops
                          .slice(-3)
                          .reverse()
                          .map((s) => `${dateTime(s.start)} ${s.reason_text.toLowerCase()} (${minutes(s.minutes)})`)
                          .join("; ")}
                      </div>
                    )}
                  </Section>
                </div>
                <div className="rounded-lg bg-panel p-4">
                  <Section title="Отчёты рабочих" aside={`${view.reports.length} последних`}>
                    {view.reports.length === 0 ? (
                      <Empty>Отчётов пока нет.</Empty>
                    ) : (
                      <ul className="flex flex-col divide-y divide-line text-sm">
                        {view.reports.slice(0, 6).map((r) => (
                          <li key={r.id} className="grid grid-cols-[110px_1fr] gap-3 py-2">
                            <div className="text-muted">
                              {dateTime(r.ts_start)}
                              <div>{r.duration_min != null ? minutes(r.duration_min) : "идёт"}</div>
                            </div>
                            <div>
                              <div className="font-medium">
                                {name(r.equipment_id)}: {r.machine_reason_text || "остановка"}
                              </div>
                              {r.status === "completed" ? (
                                <div className="text-muted">
                                  {r.reporter_role && `${r.reporter_role}: `}
                                  {sentence(r.description || "без описания")}
                                  {r.actions_taken && ` Сделано: ${sentence(r.actions_taken)}`}
                                </div>
                              ) : (
                                <button
                                  type="button"
                                  onClick={() => startReport(r.equipment_id, r.id)}
                                  className="mt-0.5 text-xs font-medium text-warn underline"
                                >
                                  Не заполнен — заполнить
                                </button>
                              )}
                            </div>
                          </li>
                        ))}
                      </ul>
                    )}
                  </Section>
                </div>
              </div>

              <div className="flex flex-col gap-4">
                <div className="rounded-lg bg-panel p-4">
                  <Section title="Причины простоев" aside={`за ${view.pareto.days} дней`}>
                    {stops.length ? <ParetoChart reasons={stops} /> : <Empty>Простоев не было.</Empty>}
                    {waiting > 0 && (
                      <p className="mt-1 text-sm text-muted">
                        Ещё {minutes(waiting)} участок ждал соседей: пустой вход или занятый выход.
                      </p>
                    )}
                    <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
                      <Swatch color="#d2352b" label="поломки и замены" />
                      <Swatch color="#2c67cc" label="плановое ТО" />
                      <Swatch color="#d59a12" label="микроостановки" />
                    </div>
                  </Section>
                </div>
                <div className="rounded-lg bg-panel p-4">
                  <Section title="OEE и брак по сменам" aside="последние 12 смен">
                    {view.kpi.history.length ? (
                      <ShiftHistoryChart
                        history={view.kpi.history}
                        oeeTarget={view.targets.oee_min}
                        defectMax={view.targets.defect_rate_max}
                      />
                    ) : (
                      <Empty>История появится после первой смены.</Empty>
                    )}
                    <div className="mt-3">
                      <KpiNote k={view.kpi.day} t={view.targets} />
                    </div>
                  </Section>
                </div>
                <div className="rounded-lg bg-panel p-4">
                  <Section title="Инциденты цеха">
                    {view.incidents.length === 0 ? (
                      <Empty>Инцидентов не было.</Empty>
                    ) : (
                      <ul className="flex flex-col divide-y divide-line text-sm">
                        {view.incidents.slice(0, 6).map((i) => (
                          <li key={i.id} className="py-2">
                            <div className="flex items-center justify-between">
                              <SeverityMark severity={i.severity} />
                              <span className="text-xs text-muted">
                                {dateTime(i.ts_start)} {i.status === "open" ? "открыт" : "закрыт"}
                              </span>
                            </div>
                            <div className="mt-0.5 font-medium">{i.title}</div>
                          </li>
                        ))}
                      </ul>
                    )}
                  </Section>
                </div>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

const sentence = (t: string) => {
  const s = t.trim();
  return /[.!?]$/.test(s) ? s : `${s}.`;
};

function Swatch({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: color }} />
      {label}
    </span>
  );
}
