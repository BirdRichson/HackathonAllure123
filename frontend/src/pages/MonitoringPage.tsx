import { api } from "../api/client";
import { C, Chart, axis, base } from "../charts/echarts";
import { Timeline } from "../charts/Timeline";
import { Empty, Section, StateChip } from "../components/ui";
import { hhmm, minutes, pct } from "../format";
import { usePoll } from "../hooks/usePoll";
import { useLive } from "../store/live";
import type { ShiftKpi } from "../types";
import { useEquipmentName } from "./PlantPage";

const MAIN: [string, string, string][] = [
  ["WELD", "Сварка", C.steel],
  ["PAINT", "Окраска", C.signal],
  ["ASSY", "Сборка", C.info],
];
const AREA_NAME: Record<string, string> = { WELD: "Сварка", PAINT: "Окраска", ASSY: "Сборка", QC: "Контроль" };

function OeeTrend({ data, target }: { data: Record<string, ShiftKpi[]>; target: number }) {
  const ref = data.WELD ?? [];
  return (
    <Chart
      style={{ height: 250 }}
      option={{
        ...base,
        grid: { left: 44, right: 16, top: 30, bottom: 28 },
        legend: { top: 0, left: 0, itemWidth: 14, itemHeight: 8, textStyle: { color: C.muted } },
        tooltip: { ...base.tooltip, valueFormatter: (v: number) => pct(v) },
        xAxis: {
          type: "category",
          data: ref.map((h) => `${h.date.slice(8, 10)}.${h.date.slice(5, 7)} см.${h.shift}`),
          ...axis,
          axisLabel: { color: C.muted, fontSize: 11 },
        },
        yAxis: { type: "value", min: 0.6, max: 1, ...axis, axisLabel: { color: C.muted, formatter: (v: number) => pct(v, 0) } },
        series: MAIN.map(([id, label, color], i) => ({
          name: label,
          type: "line",
          data: (data[id] ?? []).map((h) => h.oee),
          symbolSize: 5,
          lineStyle: { color, width: 2 },
          itemStyle: { color },
          markLine:
            i === 0
              ? {
                  silent: true,
                  symbol: "none",
                  lineStyle: { color: C.ok, type: "dashed" },
                  label: { formatter: `цель ${pct(target, 0)}`, color: C.ok, position: "insideEndTop" },
                  data: [{ yAxis: target }],
                }
              : undefined,
        })),
      }}
    />
  );
}

export function MonitoringPage() {
  const events = useLive((s) => s.events);
  const kpi = useLive((s) => s.kpi);
  const name = useEquipmentName();
  const simTime = useLive((s) => s.status?.sim_time ?? "");
  // Окно — с начала рабочего дня (08:00), но не меньше двух часов, чтобы ночь не занимала полэкрана.
  const sinceStart = simTime ? Number(simTime.slice(11, 13)) + Number(simTime.slice(14, 16)) / 60 - 8 : 8;
  const windowHours = Math.max(2, Math.min(16, sinceStart + 0.1));
  const { data: win } = usePoll(() => api.events(windowHours), [Math.round(windowHours)], 5000);
  const oldestLive = events.length ? events[events.length - 1]!.ts : "9999";
  // В ленте — аварии, ТО, переналадки и восстановление оборудования; переключения «ждёт / работает» скрыты, их видно на шкале.
  const meaningful = (e: { scope: string; state: string }) =>
    e.scope === "equipment" || !["running", "starved", "blocked", "offline"].includes(e.state);
  const feed = [...events, ...[...(win?.events ?? [])].reverse().filter((e) => e.ts < oldestLive)].filter(meaningful);
  const { data: hist } = usePoll(
    async () => Object.fromEntries(await Promise.all(MAIN.map(async ([id]) => [id, await api.kpiHistory(id, 14)] as const))),
    [],
    30000,
  );
  const { data: recon } = usePoll(() => api.reconciliation(7), [], 30000);

  const reconByArea = Object.entries(
    (recon ?? []).reduce<Record<string, { lost: number; reg: number; flow: number; shifts: number }>>((acc, r) => {
      const a = (acc[r.area_id] ??= { lost: 0, reg: 0, flow: 0, shifts: 0 });
      a.lost += r.lost_min;
      a.reg += r.registered_min + (r.breakdown.setup ?? 0); // переналадки система знает сама
      a.flow += (r.breakdown.starved ?? 0) + (r.breakdown.blocked ?? 0);
      a.shifts += 1;
      return acc;
    }, {}),
  );

  return (
    <div className="scroll-thin grid min-h-0 flex-1 grid-cols-[1fr_440px] gap-4 overflow-y-auto p-4">
      <div className="flex flex-col gap-4">
        <div className="rounded-lg bg-panel p-5">
          <Section title="Состояния участков и оборудования" aside="с начала рабочего дня, наведите на полосу">
            {win ? <Timeline win={win} names={name} /> : <Empty>Загружаю историю…</Empty>}
            <p className="mt-2 text-sm text-muted">
              Строка участка — все его состояния. Под ней оборудование: красным — аварии, синим — плановое ТО.
            </p>
          </Section>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div className="rounded-lg bg-panel p-5">
            <Section title="OEE по сменам" aside="последние 14 смен">
              {hist && kpi ? <OeeTrend data={hist} target={kpi.targets.oee_min} /> : <Empty>Загружаю…</Empty>}
            </Section>
          </div>
          <div className="rounded-lg bg-panel p-5">
            <Section title="Сверка учёта простоев" aside="7 дней">
              <p className="mb-3 text-sm text-muted">
                Сколько рабочего времени участок потерял и сколько из этого записано как простои оборудования.
              </p>
              <table className="w-full text-sm">
                <thead className="text-left text-muted">
                  <tr>
                    <th className="pb-1 font-normal">Участок</th>
                    <th className="pb-1 text-right font-normal">Потеряно</th>
                    <th className="pb-1 text-right font-normal">Записано</th>
                    <th className="pb-1 text-right font-normal">Ожидание</th>
                    <th className="pb-1 text-right font-normal">Не записано</th>
                  </tr>
                </thead>
                <tbody>
                  {reconByArea.map(([id, a]) => {
                    const unexplained = Math.max(0, a.lost - a.reg - a.flow);
                    return (
                      <tr key={id} className="border-t border-line">
                        <td className="py-2 font-medium">{AREA_NAME[id]}</td>
                        <td className="py-2 text-right">{minutes(a.lost)}</td>
                        <td className="py-2 text-right">{minutes(a.reg)}</td>
                        <td className="py-2 text-right">{minutes(a.flow)}</td>
                        <td className="py-2 text-right font-semibold" style={{ color: unexplained > 60 ? "var(--color-warn)" : undefined }}>
                          {minutes(unexplained)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <p className="mt-2 text-xs text-muted">
                «Не записано» — короткие остановки, о которых никто не сообщил. В данных завода такое расхождение тоже есть: сварка
                02.10 потеряла 48 минут, а записано 30.
              </p>
            </Section>
          </div>
        </div>
      </div>

      <div className="flex min-h-0 flex-col rounded-lg bg-panel p-5">
        <Section title="Лента событий" aside="в реальном времени" className="min-h-0 flex-1">
          {feed.length === 0 && <Empty>События появятся, как только что-то изменится на линии.</Empty>}
          <ul className="scroll-thin flex min-h-0 flex-1 flex-col divide-y divide-line overflow-y-auto text-sm">
            {feed.slice(0, 120).map((e, i) => (
              <li key={`${e.ts}-${e.id}-${i}`} className="grid grid-cols-[48px_1fr] gap-2 py-2">
                <span className="text-muted">{hhmm(e.ts)}</span>
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{e.scope === "area" ? AREA_NAME[e.area_id] ?? e.id : name(e.id)}</span>
                    <StateChip state={e.state} size="sm" />
                  </div>
                  {e.reason_text && <div className="text-muted">{e.reason_text}</div>}
                </div>
              </li>
            ))}
          </ul>
        </Section>
      </div>
    </div>
  );
}
