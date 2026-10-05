import { AiTag } from "../components/ai";
import { Section, SeverityMark, StateChip, TargetBar } from "../components/ui";
import { hhmm, int, pct } from "../format";
import { PlantMap } from "../map/PlantMap";
import { useLive } from "../store/live";
import { useUi } from "../store/ui";
import { HEX, LEVEL_COLOR, STATE } from "../theme/states";
import type { State } from "../types";

const AREAS: [string, string][] = [
  ["WELD", "Сварка"],
  ["PAINT", "Окраска"],
  ["ASSY", "Сборка"],
  ["QC", "Контроль"],
];

export function useEquipmentName() {
  const plant = useLive((s) => s.plant);
  return (id: string) => plant?.equipment.find((e) => e.id === id)?.name ?? id;
}

function KpiColumn() {
  const kpi = useLive((s) => s.kpi);
  const areas = useLive((s) => s.areas);
  const openArea = useUi((s) => s.openAreaPanel);
  if (!kpi) return <aside className="w-[340px] shrink-0" />;
  const t = kpi.targets;
  const plant = kpi.shift.plant;
  const m = kpi.month;
  const monthPlanPace = m.shifts_total ? (m.output_mtd / Math.max(m.shifts_done, 0.01)) * m.shifts_total : 0;

  return (
    <aside className="scroll-thin flex w-[340px] shrink-0 flex-col gap-5 overflow-y-auto border-r border-line bg-panel p-5">
      <Section title="OEE завода за смену" aside={`цель ${pct(t.oee_min, 0)}`} className="shrink-0">
        <div className="cond text-[64px] leading-none font-semibold" style={{ color: LEVEL_COLOR[plant.level] }}>
          {pct(plant.oee)}
        </div>
        <div className="mt-3">
          <TargetBar value={plant.oee} target={t.oee_min} />
        </div>
        <dl className="mt-3 grid grid-cols-3 gap-2 text-sm">
          {[
            ["Доступность", plant.availability],
            ["Производит.", plant.performance],
            ["Качество", plant.quality],
          ].map(([label, v]) => (
            <div key={label as string}>
              <dt className="text-muted">{label}</dt>
              <dd className="cond text-xl font-semibold">{pct(v as number)}</dd>
            </div>
          ))}
        </dl>
      </Section>

      <Section title="Выпуск" aside="готовые авто после контроля" className="shrink-0">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <div className="text-sm text-muted">Смена</div>
            <div className="cond text-[32px] leading-tight font-semibold">{int(kpi.shift.output)}</div>
            <div className="text-sm text-muted">план к {hhmm(kpi.sim_time)}: {int(kpi.shift.areas.QC?.plan_units)}</div>
          </div>
          <div>
            <div className="text-sm text-muted">Сутки</div>
            <div className="cond text-[32px] leading-tight font-semibold">{int(kpi.day.output)}</div>
            <div className="text-sm text-muted">план: {int(kpi.day.plan)}</div>
          </div>
        </div>
        <div className="mt-4 rounded-md bg-sunk p-3">
          <div className="flex items-baseline justify-between text-sm">
            <span className="font-medium">Месяц</span>
            <span className="text-muted">цель {int(m.target_month)}</span>
          </div>
          <div className="cond mt-1 text-2xl font-semibold">{int(m.output_mtd)}</div>
          <div className="mt-2">
            <TargetBar value={m.output_mtd} target={m.target_month} max={m.target_month * 1.1} color="var(--color-signal)" />
          </div>
          <div className="mt-2 text-sm text-muted">
            При текущем темпе — около {int(monthPlanPace)} к концу месяца
          </div>
        </div>
      </Section>

      <Section title="Участки" aside="смена" className="shrink-0">
        <table className="w-full text-sm">
          <thead className="text-left text-muted">
            <tr>
              <th className="pb-1 font-normal">Участок</th>
              <th className="pb-1 text-right font-normal">OEE</th>
              <th className="pb-1 text-right font-normal">Брак</th>
            </tr>
          </thead>
          <tbody>
            {AREAS.map(([id, name]) => {
              const k = kpi.shift.areas[id];
              const a = areas.find((x) => x.id === id);
              if (!k || !a) return null;
              return (
                <tr key={id} className="cursor-pointer border-t border-line hover:bg-sunk" onClick={() => openArea(id)}>
                  <td className="py-2">
                    <div className="font-medium">{name}</div>
                    <StateChip state={a.state} size="sm" />
                  </td>
                  <td className="cond py-2 text-right text-lg font-semibold" style={{ color: LEVEL_COLOR[k.level] }}>
                    {pct(k.oee, 0)}
                  </td>
                  <td
                    className="cond py-2 text-right text-lg font-semibold"
                    style={{ color: id !== "QC" && k.defect_rate > t.defect_rate_max ? "var(--color-bad)" : undefined }}
                  >
                    {id === "QC" ? "—" : pct(k.defect_rate)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <p className="mt-2 text-xs text-muted">Норма брака — не более {pct(t.defect_rate_max, 0)}.</p>
      </Section>
    </aside>
  );
}

function FeedColumn() {
  const incidents = useLive((s) => s.incidents);
  const reports = useLive((s) => s.reports);
  const startReport = useUi((s) => s.startReport);
  const openArea = useUi((s) => s.openAreaPanel);
  const name = useEquipmentName();
  const open = incidents.filter((i) => i.status === "open");
  const recentClosed = incidents.filter((i) => i.status === "closed").slice(0, 4);

  return (
    <aside className="scroll-thin flex w-[390px] shrink-0 flex-col gap-5 overflow-y-auto border-l border-line bg-panel p-5">
      <Section title="Открытые инциденты" aside={open.length ? `${open.length}` : undefined} className="shrink-0">
        {open.length === 0 && <p className="text-sm text-muted">Сейчас всё в норме.</p>}
        <ul className="flex flex-col gap-2">
          {open.slice(0, 6).map((i) => (
            <li
              key={i.id}
              className="cursor-pointer rounded-md border border-line p-3 hover:bg-sunk"
              style={{ borderLeft: `4px solid ${i.severity === "critical" ? HEX.down : i.severity === "warning" ? HEX.starved : HEX.maintenance}` }}
              onClick={() => i.area_id && openArea(i.area_id, i.equipment_id)}
            >
              <div className="flex items-center justify-between">
                <span className="flex items-center gap-2">
                  <SeverityMark severity={i.severity} />
                  {i.type === "prediction" && <AiTag title="Предупреждение ИИ до отказа" />}
                </span>
                <span className="text-xs text-muted">с {hhmm(i.ts_start)}</span>
              </div>
              <div className="mt-1 font-medium leading-snug">{i.title}</div>
              <div className="mt-0.5 text-sm text-muted">{i.details}</div>
            </li>
          ))}
        </ul>
        {recentClosed.length > 0 && (
          <div className="mt-3 text-sm">
            <div className="mb-1 text-muted">Недавно закрыты</div>
            {recentClosed.map((i) => (
              <div key={i.id} className="truncate py-0.5" title={i.title}>
                <span className="text-muted">{hhmm(i.ts_end)}</span> {i.title}
              </div>
            ))}
          </div>
        )}
      </Section>

      <Section title="Отчёты рабочих о простоях" className="shrink-0">
        <ul className="flex flex-col divide-y divide-line">
          {reports.slice(0, 7).map((r) => (
            <li key={r.id} className="py-2.5 text-sm">
              <div className="flex items-baseline justify-between gap-2">
                <span className="font-medium">{name(r.equipment_id)}</span>
                <span className="text-xs text-muted">{hhmm(r.ts_start)}</span>
              </div>
              <div className="text-muted">
                {r.machine_reason_text ? `Станок: ${r.machine_reason_text}` : "Сообщил рабочий"}
                {r.duration_min != null ? `, ${Math.round(r.duration_min)} мин` : ", идёт сейчас"}
              </div>
              {r.status === "completed" ? (
                <>
                  <div className="mt-0.5 line-clamp-2">{r.description || "Без описания"}</div>
                  {r.ai_mismatch && (
                    <div className="mt-0.5 flex items-center gap-1.5 text-xs text-bad">
                      <AiTag /> причина, похоже, указана неверно
                    </div>
                  )}
                </>
              ) : (
                <button
                  type="button"
                  onClick={() => startReport(r.equipment_id, r.id)}
                  className="mt-1 rounded border border-warn px-2 py-0.5 text-xs font-medium text-warn hover:bg-[#fbf1d9]"
                >
                  Не заполнен — заполнить отчёт
                </button>
              )}
            </li>
          ))}
        </ul>
      </Section>
    </aside>
  );
}

function Legend() {
  const items: State[] = ["running", "starved", "idle", "down", "maintenance", "offline"];
  return (
    <div className="pointer-events-none absolute bottom-3 left-4 flex flex-wrap gap-x-4 gap-y-1 rounded-md bg-panel/90 px-3 py-2 text-xs text-muted">
      {items.map((s) => (
        <span key={s} className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: HEX[s] }} />
          {STATE[s].label}
        </span>
      ))}
      <span>Нажмите на цех, чтобы открыть его. Планировка условная: схема участков — из данных завода, расстановка — допущение модели</span>
    </div>
  );
}

export function PlantPage() {
  return (
    <div className="flex min-h-0 flex-1">
      <KpiColumn />
      <main className="relative min-w-0 flex-1">
        <PlantMap />
        <Legend />
      </main>
      <FeedColumn />
    </div>
  );
}
