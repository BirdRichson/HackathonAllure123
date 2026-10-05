import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";

import { pct } from "../format";
import { onUnits, useLive } from "../store/live";
import { useUi } from "../store/ui";
import { BODY, HEX, STATE } from "../theme/states";
import type { AreaBrief, EquipmentBrief, State } from "../types";
import { bufferModels, current, onFlow } from "./flow";
import { P, shade } from "./iso";
import {
  BELT_A_Y,
  BELT_B_Y,
  BUFFERS,
  CONVEYOR_SPANS,
  PLACEMENTS,
  type Placement,
  ROOMS,
  type Room,
  STATIONS,
  TURN_X,
  WALL_H,
  pathPoint,
} from "./layout";
import {
  BodyShape,
  Booth,
  ConveyorDrive,
  IsoBox,
  Oven,
  Rack,
  Robot,
  StandBox,
  StandGate,
  translate,
} from "./shapes";

const AREA_NAMES: Record<string, string> = {
  WH: "Склад комплектующих",
  WELD: "Сварка",
  PAINT: "Окраска",
  ASSY: "Сборка",
  QC: "Контроль качества",
  FG: "Склад готовой продукции",
};

const FLOOR: Partial<Record<State, string>> = {
  down: "#fbe4e1",
  maintenance: "#e5edfb",
  setup: "#e5edfb",
  starved: "#fbf2dc",
  blocked: "#fbf2dc",
  offline: "#eceff2",
};

function viewBox(): string {
  const xs: number[] = [];
  const ys: number[] = [];
  for (const x of [-1.5, 33]) for (const y of [-1.5, 23.5]) for (const z of [-0.6, 4.2]) {
    const [a, b] = P(x, y, z);
    xs.push(a);
    ys.push(b);
  }
  const minX = Math.min(...xs) - 10;
  const minY = Math.min(...ys) - 10;
  return `${minX} ${minY} ${Math.max(...xs) - minX + 10} ${Math.max(...ys) - minY + 10}`;
}

// ─────────────────────────────── пол и стены ─────────────────────────────────

function Ground() {
  const lines: ReactNode[] = [];
  for (let x = -1; x <= 33; x += 2) {
    const [a, b] = [P(x, -1.5, -0.4), P(x, 23.5, -0.4)];
    lines.push(<line key={`x${x}`} x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} />);
  }
  for (let y = -1; y <= 23.5; y += 2) {
    const [a, b] = [P(-1.5, y, -0.4), P(33, y, -0.4)];
    lines.push(<line key={`y${y}`} x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} />);
  }
  return (
    <g>
      <polygon
        points={[P(-1.5, -1.5, -0.4), P(33, -1.5, -0.4), P(33, 23.5, -0.4), P(-1.5, 23.5, -0.4)].map((p) => p.join(",")).join(" ")}
        fill="#dde2e7"
      />
      <g stroke="#d2d8de" strokeWidth={0.8}>{lines}</g>
    </g>
  );
}

function Floor({ room, state, onClick }: { room: Room; state: State | undefined; onClick?: () => void }) {
  const fill = (state && FLOOR[state]) || "#f6f7f9";
  const strokeColor = state && state !== "running" && state !== "offline" ? HEX[state] : "#c6ced6";
  return (
    <g className={onClick ? "cursor-pointer" : undefined} onClick={onClick}>
      <IsoBox box={{ x: room.x, y: room.y, z: -0.35, w: room.w, d: room.d, h: 0.35 }} color={fill} stroke={strokeColor} />
    </g>
  );
}

function Walls({ room }: { room: Room }) {
  const beltY = room.row === "A" ? BELT_A_Y : BELT_B_Y;
  const color = "#eceff2";
  const t = 0.22;
  return (
    <g pointerEvents="none">
      <IsoBox box={{ x: room.x - t, y: room.y - t, w: room.w + t, d: t, h: WALL_H }} color={color} stroke="#b9c2cb" />
      <IsoBox box={{ x: room.x - t, y: room.y, w: t, d: beltY - 0.85 - room.y, h: WALL_H }} color={color} stroke="#b9c2cb" />
      <IsoBox
        box={{ x: room.x - t, y: beltY + 0.85, w: t, d: room.y + room.d - beltY - 0.85, h: WALL_H }}
        color={color}
        stroke="#b9c2cb"
      />
    </g>
  );
}

// ─────────────────────────────── лента ───────────────────────────────────────

function Belt({ row }: { row: "A" | "B" }) {
  const c = "#55616d";
  if (row === "A") {
    return (
      <g pointerEvents="none">
        <IsoBox box={{ x: 0.6, y: BELT_A_Y - 0.5, w: TURN_X + 0.5 - 0.6, d: 1, h: 0.22 }} color={c} />
        <IsoBox box={{ x: TURN_X - 0.5, y: BELT_A_Y + 0.5, w: 1, d: BELT_B_Y - BELT_A_Y - 0.5, h: 0.22 }} color={c} />
      </g>
    );
  }
  return (
    <g pointerEvents="none">
      <IsoBox box={{ x: 0.6, y: BELT_B_Y - 0.5, w: TURN_X + 0.5 - 0.6, d: 1, h: 0.22 }} color={c} />
    </g>
  );
}

function ConveyorStripes({ equipment }: { equipment: EquipmentBrief[] }) {
  return (
    <g pointerEvents="none">
      {Object.entries(CONVEYOR_SPANS).map(([id, [x0, x1]]) => {
        const st = equipment.find((e) => e.id === id)?.state;
        if (!st || st === "running" || st === "offline" || st === "idle") return null;
        return (
          <polygon
            key={id}
            points={[P(x0, BELT_B_Y - 0.5, 0.23), P(x1, BELT_B_Y - 0.5, 0.23), P(x1, BELT_B_Y + 0.5, 0.23), P(x0, BELT_B_Y + 0.5, 0.23)]
              .map((p) => p.join(","))
              .join(" ")}
            fill={HEX[st]}
            opacity={0.75}
          />
        );
      })}
    </g>
  );
}

// ─────────────────────────────── оборудование ────────────────────────────────

function EquipmentShape({ p, onClick }: { p: Placement; onClick: () => void }) {
  let shape: ReactNode = null;
  if (p.kind === "robot") shape = <Robot x={p.x} y={p.y} side={p.side} />;
  else if (p.kind === "booth") shape = <Booth {...p} />;
  else if (p.kind === "oven") shape = <Oven {...p} />;
  else if (p.kind === "conveyor") shape = <ConveyorDrive x={p.x} y={p.y} w={p.w} />;
  else if (p.kind === "stand_gate") shape = <StandGate {...p} />;
  else shape = <StandBox {...p} />;
  return (
    <g className="cursor-pointer" onClick={onClick}>
      {shape}
    </g>
  );
}

function Decor() {
  // Рабочие места сборки и стеллажи склада — без данных, для узнаваемости.
  return (
    <g pointerEvents="none">
      {[15.4, 20.4, 25.4].map((x) => (
        <IsoBox key={x} box={{ x, y: 18.9, w: 1.8, d: 0.8, h: 0.7 }} color="#e4e8ec" />
      ))}
    </g>
  );
}

// ─────────────────────────────── кузова ──────────────────────────────────────

function bodyColor(area: string, model: string | null): string {
  if (area === "WELD" || area === "PAINT_IN") return BODY.metal;
  return (model && BODY.models[model]) || BODY.models["Chevrolet Cobalt"]!;
}

function BufferBodies({ area, count, capacity }: { area: string; count: number; capacity: number | null }) {
  const buf = BUFFERS[area];
  if (!buf) return null;
  const spacing = 1.55;
  const fits = Math.max(0, Math.floor((buf.to - buf.from) / spacing) + 1);
  const shown = Math.min(count, fits);
  const models = bufferModels(area, shown);
  const bodies: ReactNode[] = [];
  for (let i = 0; i < shown; i++) {
    const s = buf.to - i * spacing;
    const p = pathPoint(s);
    const color = area === "PAINT" ? BODY.metal : bodyColor(area, models[shown - 1 - i] ?? null);
    bodies.push(
      <g key={i} transform={translate(p.x, p.y)}>
        <BodyShape color={color} alongX={p.alongX} />
      </g>,
    );
  }
  const mid = pathPoint((buf.from + buf.to) / 2);
  const [bx, by] = P(mid.x + (mid.alongX ? 0 : 1.1), mid.y + (mid.alongX ? 1.3 : 0), 0.3);
  return (
    <g pointerEvents="none">
      {bodies}
      <g transform={`translate(${bx},${by})`}>
        <rect x={-24} y={-10} width={48} height={20} rx={10} fill="#ffffff" stroke="#c6ced6" />
        <text textAnchor="middle" y={4.5} fontSize={12} fill="#3d4955" fontWeight={500}>
          {capacity ? `${count}/${capacity}` : count}
        </text>
      </g>
    </g>
  );
}

/** Кузов на станции: едет от входа к выходу за время цикла (с учётом скорости), стоит, если участок стоит. */
function MovingBodies({ ids }: { ids: string[] }) {
  const refs = useRef<Record<string, SVGGElement | null>>({});
  const [, setV] = useState(0);

  useEffect(() => onFlow(() => setV((v) => v + 1)), []);

  useEffect(() => {
    const phase: Record<string, number> = {};
    const off = onUnits((units) => {
      for (const u of units) if (ids.includes(u.area_id)) phase[u.area_id] = 0;
    });
    let raf = 0;
    let last = performance.now();
    const loop = (now: number) => {
      const dt = Math.min(0.5, (now - last) / 1000);
      last = now;
      const st = useLive.getState();
      const speed = st.status && !st.status.paused ? st.status.speed : 0;
      for (const id of ids) {
        const g = refs.current[id];
        const area = st.areas.find((a) => a.id === id);
        const stn = STATIONS[id];
        if (!g || !area || !stn) continue;
        const cycleMin = st.plant?.process[id]?.cycle_min ?? 3.9;
        const T = (cycleMin * 60) / Math.max(speed, 1e-6);
        if (area.state === "running" && speed > 0) phase[id] = Math.min(0.96, (phase[id] ?? 0.35) + dt / T);
        const s = stn.entry + (stn.exit - stn.entry) * (phase[id] ?? 0.35);
        const p = pathPoint(s);
        g.setAttribute("transform", translate(p.x, p.y));
        g.style.display = area.state === "offline" ? "none" : "";
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(raf);
      off();
    };
  }, [ids]);

  return (
    <g pointerEvents="none">
      {ids.map((id) => (
        <g key={id} ref={(el) => void (refs.current[id] = el)}>
          <BodyShape color={bodyColor(id, current[id] ?? null)} alongX />
        </g>
      ))}
    </g>
  );
}

function ParkedCars({ count }: { count: number }) {
  const spots: [number, number][] = [];
  for (const y of [14.4, 15.6, 19.6, 20.8]) for (const x of [1.0, 2.6]) spots.push([x, y]);
  const colors = ["Chevrolet Onix", "Chevrolet Cobalt", "Chevrolet Onix", "JAC J7", "Chevrolet Cobalt", "Chevrolet Onix", "Chevrolet Cobalt", "Chevrolet Onix"];
  const n = Math.min(spots.length, Math.max(2, Math.round(count / 30)));
  return (
    <g pointerEvents="none">
      {spots.slice(0, n).map(([x, y], i) => (
        <g key={i} transform={translate(x + 0.6, y)}>
          <BodyShape color={BODY.models[colors[i]!]!} alongX />
        </g>
      ))}
    </g>
  );
}

// ─────────────────────────────── подписи ─────────────────────────────────────

function RoomLabel({ room, area, lines }: { room: Room; area?: AreaBrief; lines: ReactNode[] }) {
  // Верхний ряд подписываем над дальней стеной, нижний — у ближнего края, где свободно.
  const [x, y] =
    room.row === "A" ? P(room.x + 0.2, room.y - 0.3, WALL_H + 1.1) : P(room.x - 0.4, room.y + room.d + 0.8, 0);
  const st = area?.state;
  const color = st && st !== "running" ? HEX[st] : "#3d4955";
  return (
    <g transform={`translate(${x},${y})`} pointerEvents="none">
      <rect x={-6} y={-22} width={196} height={lines.length > 0 ? 46 : 28} rx={6} fill="#ffffff" stroke="#c6ced6" />
      <rect x={-6} y={-22} width={4} height={lines.length > 0 ? 46 : 28} rx={2} fill={color} />
      <text x={6} y={-3} fontSize={16} fontWeight={600} fill="#1c2630" style={{ fontFamily: "var(--font-cond)" }}>
        {AREA_NAMES[room.id]}
      </text>
      {lines.length > 0 && (
        <text x={6} y={16} fontSize={12.5} fill="#59656f">
          {lines}
        </text>
      )}
    </g>
  );
}

function Pin({ p, eq, onClick }: { p: Placement; eq: EquipmentBrief; onClick: () => void }) {
  const [x, y] = P(p.x + p.w / 2, p.y + p.d / 2, p.h + 0.9);
  const [bx, by] = P(p.x + p.w / 2, p.y + p.d / 2, p.h);
  const st = STATE[eq.state];
  // Подпись с текстом — только для собственных остановок оборудования; ожидание видно по цвету маркера.
  const alert = eq.state === "down" || eq.state === "maintenance" || eq.state === "setup";
  const label = alert ? `${eq.name}: ${st.label.toLowerCase()}` : eq.name;
  const width = Math.max(56, label.length * 6.8 + 14);
  return (
    <g className="cursor-pointer" onClick={onClick}>
      <line x1={bx} y1={by} x2={x} y2={y} stroke="#8b96a1" strokeWidth={1} />
      {eq.state === "down" && <circle cx={x} cy={y} r={9} fill="none" stroke={HEX.down} strokeWidth={3} className="alarm-ring" />}
      <circle cx={x} cy={y} r={8.5} fill={HEX[eq.state]} stroke="#ffffff" strokeWidth={2} />
      <text x={x} y={y + 3.6} textAnchor="middle" fontSize={10} fill="#ffffff" fontWeight={700}>
        {st.icon}
      </text>
      <g transform={`translate(${x + 13},${y - 10})`}>
        <rect width={width} height={20} rx={4} fill={alert ? HEX[eq.state] : "#ffffff"} stroke={alert ? "none" : "#c6ced6"} opacity={0.96} />
        <text x={7} y={14} fontSize={12} fill={alert ? "#ffffff" : "#3d4955"} fontWeight={alert ? 600 : 500}>
          {label}
        </text>
      </g>
    </g>
  );
}

// ─────────────────────────────── карта ───────────────────────────────────────

export function PlantMap() {
  const areas = useLive((s) => s.areas);
  const equipment = useLive((s) => s.equipment);
  const kpi = useLive((s) => s.kpi);
  const openArea = useUi((s) => s.openAreaPanel);
  const vb = useMemo(viewBox, []);

  const area = (id: string) => areas.find((a) => a.id === id);
  const eqById = new Map(equipment.map((e) => [e.id, e]));
  const roomsA = ROOMS.filter((r) => r.row === "A");
  const roomsB = ROOMS.filter((r) => r.row === "B");
  const clickable = (id: string) => (["WELD", "PAINT", "ASSY", "QC"].includes(id) ? () => openArea(id) : undefined);

  const placed = (rows: string[], side: Placement["side"][]) =>
    PLACEMENTS.filter((p) => rows.includes(eqById.get(p.id)?.area_id ?? "") && side.includes(p.side)).map((p) => (
      <EquipmentShape key={p.id} p={p} onClick={() => openArea(eqById.get(p.id)!.area_id, p.id)} />
    ));

  const kpiLine = (id: string): ReactNode[] => {
    const k = kpi?.shift.areas[id];
    const a = area(id);
    if (!k || !a) return [];
    const st = STATE[a.state];
    const parts: ReactNode[] = [
      <tspan key="s" fill={a.state === "running" ? "#17924f" : HEX[a.state]} fontWeight={600}>
        {a.state === "down" && a.reason_text ? a.reason_text : st.label}
      </tspan>,
      <tspan key="o">{`   OEE ${pct(k.oee, 0)}`}</tspan>,
    ];
    if (id !== "QC")
      parts.push(
        <tspan key="d" fill={k.defect_rate > (kpi?.targets.defect_rate_max ?? 0.02) ? "#d2352b" : undefined}>
          {`   брак ${pct(k.defect_rate)}`}
        </tspan>,
      );
    return parts;
  };

  const wh = area("WELD");
  const buf = (id: string) => area(id)?.buffer_in;

  return (
    <svg viewBox={vb} className="h-full w-full select-none" role="img" aria-label="Изометрическая карта завода">
      <Ground />
      {ROOMS.map((r) => (
        <Floor key={r.id} room={r} state={area(r.id)?.state} onClick={clickable(r.id)} />
      ))}

      {/* верхний ряд: склад, сварка, окраска */}
      {roomsA.map((r) => (
        <Walls key={r.id} room={r} />
      ))}
      <Rack x={0.6} y={0.5} w={5.6} filled={Math.min(1, (wh?.stock ?? 300) / 600)} />
      <Rack x={0.6} y={6.9} w={5.6} filled={Math.min(1, (wh?.stock ?? 300) / 900)} />
      {placed(["WELD", "PAINT"], ["far"])}
      <Belt row="A" />
      {buf("PAINT") && <BufferBodies area="PAINT" count={buf("PAINT")!.count} capacity={buf("PAINT")!.capacity} />}
      {buf("ASSY") && <BufferBodies area="ASSY" count={buf("ASSY")!.count} capacity={buf("ASSY")!.capacity} />}
      <MovingBodies ids={["WELD", "PAINT"]} />
      {placed(["WELD", "PAINT"], ["near", "over"])}

      {/* нижний ряд: сборка, контроль, склад готовой продукции */}
      {roomsB.map((r) => (
        <Walls key={r.id} room={r} />
      ))}
      {placed(["ASSY", "QC"], ["far"])}
      <Belt row="B" />
      <ConveyorStripes equipment={equipment} />
      {buf("QC") && <BufferBodies area="QC" count={buf("QC")!.count} capacity={buf("QC")!.capacity} />}
      <MovingBodies ids={["ASSY", "QC"]} />
      <ParkedCars count={kpi?.day.output ?? 0} />
      {placed(["ASSY", "QC"], ["near", "over"])}
      <Decor />

      {/* подписи цехов и маркеры оборудования — поверх всего */}
      {ROOMS.map((r) => {
        let lines: ReactNode[] = kpiLine(r.id);
        if (r.id === "WH") lines = [<tspan key="w">{`Комплектов CKD: ${wh?.stock ?? "—"}`}</tspan>];
        if (r.id === "FG") lines = [<tspan key="f">{`За сутки: ${kpi?.day.output ?? "—"} авто`}</tspan>];
        return <RoomLabel key={r.id} room={r} area={area(r.id)} lines={lines} />;
      })}
      {PLACEMENTS.map((p) => {
        const eq = eqById.get(p.id);
        return eq ? <Pin key={p.id} p={p} eq={eq} onClick={() => openArea(eq.area_id, eq.id)} /> : null;
      })}
    </svg>
  );
}

export { shade };
