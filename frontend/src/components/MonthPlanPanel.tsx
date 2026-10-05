import type { Plant, Targets } from "../types";

const fmt = new Intl.NumberFormat("ru-RU");

export function MonthPlanPanel({ plant, targets }: { plant: Plant; targets: Targets }) {
  const total = plant.models.reduce((s, m) => s + m.plan_month_units, 0);
  const goal = targets.monthly_output_min;
  const gap = goal - total;

  return (
    <div className="rounded-md border border-line bg-panel p-4">
      <div className="flex items-baseline justify-between">
        <div className="text-sm text-muted">План месяца по моделям</div>
        <div className="font-mono text-sm text-muted">цель {fmt.format(goal)}</div>
      </div>
      <ul className="mt-3 flex flex-col gap-2 text-sm">
        {plant.models.map((m) => (
          <li key={m.id}>
            <div className="flex justify-between">
              <span>{m.name}</span>
              <span className="font-mono">{fmt.format(m.plan_month_units)}</span>
            </div>
            <div className="mt-1 h-1.5 rounded bg-panel-2">
              <div className="h-1.5 rounded bg-accent" style={{ width: `${(m.plan_month_units / goal) * 100}%` }} />
            </div>
          </li>
        ))}
      </ul>
      <div className="mt-3 flex justify-between border-t border-line pt-3 text-sm">
        <span>Итого {fmt.format(total)}</span>
        {gap > 0 && <span style={{ color: "var(--color-warn)" }}>▲ не хватает {fmt.format(gap)} до цели</span>}
      </div>
    </div>
  );
}
