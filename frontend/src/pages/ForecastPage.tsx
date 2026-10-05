import { Empty, MaintenanceBar, Section, StateChip, TargetBar } from "../components/ui";
import { dateTime, hours, int, num } from "../format";
import { useLive } from "../store/live";
import { useUi } from "../store/ui";

const AREA_NAME: Record<string, string> = { WELD: "Сварка", PAINT: "Окраска", ASSY: "Сборка", QC: "Контроль" };

function MonthCard() {
  const kpi = useLive((s) => s.kpi);
  if (!kpi) return null;
  const m = kpi.month;
  const perShift = m.shifts_done > 0 ? m.output_mtd / m.shifts_done : 0;
  const projected = perShift * m.shifts_total;
  const gap = projected - m.target_month;
  const needPerShift = m.shifts_total > m.shifts_done ? (m.target_month - m.output_mtd) / (m.shifts_total - m.shifts_done) : 0;
  return (
    <div className="rounded-lg bg-panel p-5">
      <Section title="Выполним ли месяц?" aside={`цель — не менее ${int(m.target_month)} авто`}>
        <div className="grid grid-cols-3 gap-6">
          <div>
            <div className="text-sm text-muted">Выпущено с начала месяца</div>
            <div className="cond text-[44px] leading-tight font-semibold">{int(m.output_mtd)}</div>
            <div className="text-sm text-muted">план к этому моменту: {int(m.plan_mtd)}</div>
          </div>
          <div>
            <div className="text-sm text-muted">Если темп сохранится</div>
            <div
              className="cond text-[44px] leading-tight font-semibold"
              style={{ color: gap >= 0 ? "var(--color-ok)" : "var(--color-bad)" }}
            >
              {int(projected)}
            </div>
            <div className="text-sm text-muted">
              {gap >= 0 ? `запас ${int(gap)} авто` : `не хватит ${int(-gap)} авто`} к концу месяца
            </div>
          </div>
          <div>
            <div className="text-sm text-muted">Нужно в каждую оставшуюся смену</div>
            <div className="cond text-[44px] leading-tight font-semibold">{num(needPerShift, 0)}</div>
            <div className="text-sm text-muted">сейчас в среднем {num(perShift, 1)} за смену</div>
          </div>
        </div>
        <div className="mt-4">
          <TargetBar value={projected} target={m.target_month} max={m.target_month * 1.15} color="var(--color-signal)" />
          <div className="mt-2 text-sm text-muted">
            Прошло {num(m.shifts_done, 1)} из {m.shifts_total} рабочих смен месяца. Смены — по 8 часов, две в сутки, в будни.
          </div>
        </div>
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
    <div className="scroll-thin grid min-h-0 flex-1 grid-cols-[1.1fr_1fr] gap-4 overflow-y-auto p-4">
      <div className="flex flex-col gap-4">
        <MonthCard />
        <div className="rounded-lg bg-panel p-5">
          <Section title="Выводы ИИ">
            <Empty>Анализ отчётов рабочих и прогноз отказов подключаются — здесь появятся выводы с рекомендациями и эффектом.</Empty>
          </Section>
        </div>
      </div>
      <MaintenanceList />
    </div>
  );
}
