import { hhmm } from "../format";
import { HEX, STATE } from "../theme/states";
import type { EventsWindow, State } from "../types";

interface Row {
  key: string;
  label: string;
  indent: boolean;
  segments: { a: number; b: number; state: State; text: string }[];
}

const AREA_ORDER = ["WELD", "PAINT", "ASSY", "QC"];
const AREA_NAMES: Record<string, string> = { WELD: "Сварка", PAINT: "Окраска", ASSY: "Сборка", QC: "Контроль" };

/**
 * Временная шкала смены: для участка — все состояния, для оборудования — только его собственные
 * остановки (авария, ТО) поверх серой полосы «исправно».
 */
export function Timeline({ win, names }: { win: EventsWindow; names: (id: string) => string }) {
  const t0 = Date.parse(win.from);
  const t1 = Date.parse(win.to);
  const span = Math.max(1, t1 - t0);

  const byObj = new Map<string, { scope: string; area: string; ev: { t: number; state: State; text: string }[] }>();
  for (const e of [...win.initial, ...win.events]) {
    const k = `${e.scope}:${e.id}`;
    if (!byObj.has(k)) byObj.set(k, { scope: e.scope, area: e.area_id, ev: [] });
    byObj.get(k)!.ev.push({ t: Math.max(t0, Date.parse(e.ts)), state: e.state, text: e.reason_text });
  }

  const rows: Row[] = [];
  for (const areaId of AREA_ORDER) {
    const objs = [...byObj.entries()].filter(([, o]) => o.area === areaId);
    const area = objs.find(([k]) => k === `area:${areaId}`);
    const toSegs = (ev: { t: number; state: State; text: string }[]) =>
      ev
        .sort((x, y) => x.t - y.t)
        .map((e, i) => ({ a: e.t, b: i + 1 < ev.length ? ev[i + 1]!.t : t1, state: e.state, text: e.text }))
        .filter((s) => s.b > s.a);
    if (area) rows.push({ key: area[0], label: AREA_NAMES[areaId]!, indent: false, segments: toSegs(area[1].ev) });
    for (const [k, o] of objs.sort(([a], [b]) => a.localeCompare(b))) {
      if (o.scope !== "equipment") continue;
      rows.push({
        key: k,
        label: names(k.split(":")[1]!),
        indent: true,
        segments: toSegs(o.ev).filter((s) => s.state === "down" || s.state === "maintenance"),
      });
    }
  }

  const W = 1000;
  const L = 150;
  const H = 22;
  const gap = 6;
  const x = (t: number) => L + ((t - t0) / span) * (W - L);
  const ticks: number[] = [];
  const hour = 3600_000;
  for (let t = Math.ceil(t0 / hour) * hour; t <= t1; t += hour) ticks.push(t);
  const height = rows.length * (H + gap) + 26;

  return (
    <svg viewBox={`0 0 ${W} ${height}`} className="w-full" role="img" aria-label="Состояния оборудования за смену">
      {ticks.map((t) => (
        <g key={t}>
          <line x1={x(t)} x2={x(t)} y1={0} y2={height - 20} stroke="#eceff2" />
          <text x={x(t)} y={height - 6} textAnchor="middle" fontSize={11} fill="#59656f">
            {hhmm(new Date(t + 5 * hour).toISOString())}
          </text>
        </g>
      ))}
      {rows.map((r, i) => {
        const y = i * (H + gap);
        return (
          <g key={r.key}>
            <text x={r.indent ? 14 : 0} y={y + 15} fontSize={r.indent ? 12 : 13} fontWeight={r.indent ? 400 : 600} fill="#1c2630">
              {r.label}
            </text>
            <rect x={L} y={y + (r.indent ? 6 : 2)} width={W - L} height={r.indent ? 10 : 18} fill="#eceff2" rx={2} />
            {r.segments.map((s, j) => (
              <rect
                key={j}
                x={x(s.a)}
                y={y + (r.indent ? 6 : 2)}
                width={Math.max(1.5, x(s.b) - x(s.a))}
                height={r.indent ? 10 : 18}
                fill={s.state === "offline" ? "#dfe3e7" : HEX[s.state]}
                opacity={s.state === "running" ? 0.55 : 1}
              >
                <title>{`${STATE[s.state].label}${s.text ? `: ${s.text}` : ""}, ${hhmm(new Date(s.a + 5 * hour).toISOString())}–${hhmm(
                  new Date(s.b + 5 * hour).toISOString(),
                )}`}</title>
              </rect>
            ))}
          </g>
        );
      })}
    </svg>
  );
}
