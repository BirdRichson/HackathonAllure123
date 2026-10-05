// Изометрическая проекция. План завода — в «метрах-клетках» (x вдоль линии, y поперёк),
// экран — пиксели. Ось x уходит вправо-вниз, y — влево-вниз, z — вверх.

export const S = 24; // пикселей на клетку плана
const COS = Math.cos(Math.PI / 6);

export type Pt = [number, number];

export function P(x: number, y: number, z = 0): Pt {
  return [(x - y) * COS * S, ((x + y) * 0.5 - z) * S];
}

export const pts = (arr: Pt[]): string => arr.map(([a, b]) => `${a.toFixed(1)},${b.toFixed(1)}`).join(" ");

export interface Box {
  x: number;
  y: number;
  z?: number;
  w: number; // вдоль x
  d: number; // вдоль y
  h: number; // высота
}

/** Видимые грани коробки: верх, грань к зрителю по y (левая) и по x (правая). */
export function faces(b: Box): { top: string; left: string; right: string } {
  const z = b.z ?? 0;
  const { x, y, w, d, h } = b;
  return {
    top: pts([P(x, y, z + h), P(x + w, y, z + h), P(x + w, y + d, z + h), P(x, y + d, z + h)]),
    left: pts([P(x, y + d, z), P(x + w, y + d, z), P(x + w, y + d, z + h), P(x, y + d, z + h)]),
    right: pts([P(x + w, y, z), P(x + w, y + d, z), P(x + w, y + d, z + h), P(x + w, y, z + h)]),
  };
}

/** Прямоугольник на грани +y (обращённой к зрителю слева) — окна, полосы, надписи на стенах. */
export function leftFaceRect(x0: number, x1: number, y: number, z0: number, z1: number): string {
  return pts([P(x0, y, z0), P(x1, y, z0), P(x1, y, z1), P(x0, y, z1)]);
}

/** Затемнить или осветлить hex-цвет: k < 0 — темнее. */
export function shade(hex: string, k: number): string {
  const n = parseInt(hex.slice(1), 16);
  const ch = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((c) =>
    Math.round(k < 0 ? c * (1 + k) : c + (255 - c) * k),
  );
  return `#${ch.map((c) => c.toString(16).padStart(2, "0")).join("")}`;
}
