// Какие модели сейчас в буферах и на станциях — чтобы кузова на карте были «своего» цвета.
// Источник — события «кузов закончил цикл на участке» из живого потока.

import { onUnits } from "../store/live";

const NEXT: Record<string, string> = { WELD: "PAINT", PAINT: "ASSY", ASSY: "QC", QC: "FG" };

/** Очереди моделей во входных буферах участков: голова — следующий на вход. */
export const queues: Record<string, (string | null)[]> = { PAINT: [], ASSY: [], QC: [], FG: [] };
/** Модель кузова, который сейчас обрабатывается на участке. */
export const current: Record<string, string | null> = { WELD: null, PAINT: null, ASSY: null, QC: null };

let version = 0;
const listeners = new Set<() => void>();
export const onFlow = (fn: () => void) => {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
};
export const flowVersion = () => version;

onUnits((units) => {
  for (const u of units) {
    const next = NEXT[u.area_id];
    if (next) queues[next]!.push(u.model);
    if (u.area_id in current) {
      const q = queues[u.area_id];
      current[u.area_id] = q && q.length ? (q.shift() ?? null) : u.model;
    }
  }
  for (const q of Object.values(queues)) if (q.length > 60) q.splice(0, q.length - 60);
  version++;
  listeners.forEach((fn) => fn());
});

/** Модели последних `n` кузовов в буфере (сервер знает только количество — недостающие без модели). */
export function bufferModels(area: string, n: number): (string | null)[] {
  const q = queues[area] ?? [];
  const tail = q.slice(Math.max(0, q.length - n));
  return [...Array(Math.max(0, n - tail.length)).fill(null), ...tail];
}
