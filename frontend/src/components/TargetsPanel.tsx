import type { Targets } from "../types";

const fmt = new Intl.NumberFormat("ru-RU");

export function TargetsPanel({ targets }: { targets: Targets }) {
  const items = [
    { label: "OEE", value: `≥ ${Math.round(targets.oee_min * 100)}%`, note: "по участку и заводу" },
    { label: "Брак", value: `≤ ${Math.round(targets.defect_rate_max * 100)}%`, note: "по участку за смену" },
    {
      label: "Простой критического оборудования",
      value: `≤ ${targets.critical_downtime_max_min_per_day} мин`,
      note: "в сутки на единицу",
    },
    { label: "Выпуск", value: `≥ ${fmt.format(targets.monthly_output_min)}`, note: "автомобилей в месяц" },
  ];

  return (
    <div className="grid grid-cols-4 gap-3">
      {items.map((it) => (
        <div key={it.label} className="rounded-md border border-line bg-panel p-4">
          <div className="text-sm text-muted">{it.label}</div>
          <div className="mt-1 font-mono text-3xl">{it.value}</div>
          <div className="mt-1 text-sm text-muted">{it.note}</div>
        </div>
      ))}
    </div>
  );
}
