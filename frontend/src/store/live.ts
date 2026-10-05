import { create } from "zustand";

import { api } from "../api/client";
import type {
  AiBrief,
  AreaBrief,
  InsightsState,
  Predictions,
  EquipmentBrief,
  Incident,
  KpiNow,
  Maintenance,
  Plant,
  Report,
  ShiftInfo,
  Snapshot,
  StateEvent,
  Status,
  Tick,
  UnitEvent,
} from "../types";

type Connection = "connecting" | "online" | "offline";

interface LiveState {
  connection: Connection;
  plant: Plant | null;
  status: Status | null;
  shift: ShiftInfo | null;
  areas: AreaBrief[];
  equipment: EquipmentBrief[];
  kpi: KpiNow | null;
  incidents: Incident[];
  reports: Report[];
  events: StateEvent[];
  /** Растёт с каждым тиком — компоненты, которым нужна свежесть (страница цеха), подписываются на него. */
  tickSeq: number;
  /** Растёт при новом отчёте или инциденте — повод перезапросить списки. */
  journalSeq: number;
  predictions: Predictions | null;
  insights: InsightsState | null;
  ai: AiBrief | null;
}

const MAX_EVENTS = 400;

export const useLive = create<LiveState>(() => ({
  connection: "connecting",
  plant: null,
  status: null,
  shift: null,
  areas: [],
  equipment: [],
  kpi: null,
  incidents: [],
  reports: [],
  events: [],
  tickSeq: 0,
  journalSeq: 0,
  predictions: null,
  insights: null,
  ai: null,
}));

function mergeById<T extends { id: string }>(list: T[], updates: T[], sortKey: keyof T, limit: number): T[] {
  if (!updates.length) return list;
  const map = new Map(list.map((x) => [x.id, x]));
  for (const u of updates) map.set(u.id, { ...map.get(u.id), ...u });
  return [...map.values()].sort((a, b) => String(b[sortKey]).localeCompare(String(a[sortKey]))).slice(0, limit);
}

// Подписка на кузова, закончившие цикл, — для анимации на карте без перерисовки React.
type UnitListener = (units: UnitEvent[]) => void;
const unitListeners = new Set<UnitListener>();
export const onUnits = (fn: UnitListener) => {
  unitListeners.add(fn);
  return () => {
    unitListeners.delete(fn);
  };
};

function applySnapshot(s: Snapshot) {
  const incidents = mergeById(s.recent_incidents, s.incidents, "ts_start", 80);
  useLive.setState((st) => ({
    status: { sim_time: s.sim_time, speed: s.speed, paused: s.paused, speeds: s.speeds, seed: s.seed },
    shift: s.shift,
    areas: s.areas,
    equipment: s.equipment,
    kpi: s.kpi,
    incidents,
    reports: s.reports,
    events: [],
    tickSeq: st.tickSeq + 1,
    journalSeq: st.journalSeq + 1,
    predictions: s.predictions,
    ai: s.ai,
    insights: null,
  }));
  api.insights().then((ins) => useLive.setState({ insights: ins })).catch(() => {});
}

function applyTick(t: Tick) {
  useLive.setState((st) => {
    const eqUpdate = new Map(t.equipment.map((e) => [e.id, e]));
    return {
      status: { sim_time: t.sim_time, speed: t.speed, paused: t.paused, speeds: t.speeds, seed: t.seed },
      areas: t.areas,
      equipment: st.equipment.map((e) => ({ ...e, ...(eqUpdate.get(e.id) ?? {}) })),
      events: t.events.length ? [...t.events.reverse(), ...st.events].slice(0, MAX_EVENTS) : st.events,
      incidents: mergeById(st.incidents, t.incidents, "ts_start", 80),
      reports: mergeById(st.reports, t.reports, "ts_start", 60),
      tickSeq: st.tickSeq + 1,
      journalSeq: t.reports.length || t.incidents.length ? st.journalSeq + 1 : st.journalSeq,
    };
  });
  if (t.units.length) unitListeners.forEach((fn) => fn(t.units));
}

function applyMaintenance(list: Maintenance[]) {
  const byId = new Map(list.map((m) => [m.equipment_id, m]));
  useLive.setState((st) => ({
    equipment: st.equipment.map((e) => ({ ...e, maintenance: byId.get(e.id) ?? e.maintenance })),
  }));
}

let socket: WebSocket | null = null;
let retry = 1000;

export function connectLive() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${proto}://${location.host}/ws/live`);
  socket.onopen = () => {
    retry = 1000;
    useLive.setState({ connection: "online" });
  };
  socket.onmessage = (ev) => {
    const msg = JSON.parse(ev.data as string) as { type: string; payload: unknown };
    if (msg.type === "snapshot") applySnapshot(msg.payload as Snapshot);
    else if (msg.type === "tick") applyTick(msg.payload as Tick);
    else if (msg.type === "kpi") {
      const k = msg.payload as KpiNow;
      useLive.setState({ kpi: k, shift: k.shift });
    } else if (msg.type === "status") useLive.setState({ status: msg.payload as Status });
    else if (msg.type === "predictions") useLive.setState({ predictions: msg.payload as Predictions });
    else if (msg.type === "insights") useLive.setState({ insights: msg.payload as InsightsState });
  };
  socket.onclose = () => {
    useLive.setState({ connection: "offline" });
    setTimeout(connectLive, retry);
    retry = Math.min(retry * 2, 5000);
  };
}

export async function initLive() {
  connectLive();
  try {
    useLive.setState({ plant: await api.plant() });
  } catch {
    /* сервер ещё прогревается — данные придут со снимком */
  }
  // Часы до ТО меняются медленно: обновляем раз в 15 секунд.
  setInterval(() => {
    if (useLive.getState().connection === "online") api.maintenance().then(applyMaintenance).catch(() => {});
  }, 15000);
}

export const areaById = (id: string) => useLive.getState().areas.find((a) => a.id === id);
