// Планировка завода на карте. Схема — из данных организаторов:
// склад комплектующих → сварка → окраска → (поворот конвейера) → сборка → контроль → склад готовой продукции.
// Размеры и расстановка оборудования — условные (допущение модели), не чертёж завода.

export interface Room {
  id: string;
  x: number;
  y: number;
  w: number;
  d: number;
  row: "A" | "B";
  /** Где лента входит в зал по оси x — для проёма в боковой стене. */
}

export const BELT_A_Y = 4.5; // лента верхнего ряда
export const BELT_B_Y = 17.5; // лента нижнего ряда
export const TURN_X = 31; // поворот ленты между рядами
export const WALL_H = 1.5;

export const ROOMS: Room[] = [
  { id: "WH", x: 0, y: 0, w: 7, d: 9, row: "A" },
  { id: "WELD", x: 8, y: 0, w: 9.5, d: 9, row: "A" },
  { id: "PAINT", x: 18.5, y: 0, w: 11, d: 9, row: "A" },
  { id: "ASSY", x: 14, y: 13, w: 16, d: 9, row: "B" },
  { id: "QC", x: 6, y: 13, w: 7, d: 9, row: "B" },
  { id: "FG", x: 0, y: 13, w: 5, d: 9, row: "B" },
];

// Лента — ломаная: верхний ряд слева направо, поворот, нижний ряд справа налево.
export const PATH: [number, number][] = [
  [1, BELT_A_Y],
  [TURN_X, BELT_A_Y],
  [TURN_X, BELT_B_Y],
  [1, BELT_B_Y],
];

const SEG = [TURN_X - 1, BELT_B_Y - BELT_A_Y, TURN_X - 1]; // длины участков ломаной
export const PATH_LEN = SEG[0]! + SEG[1]! + SEG[2]!;

/** Точка на ленте по пройденному расстоянию s и направление (true — вдоль x). */
export function pathPoint(s: number): { x: number; y: number; alongX: boolean } {
  const a = SEG[0]!;
  const b = a + SEG[1]!;
  if (s <= a) return { x: 1 + s, y: BELT_A_Y, alongX: true };
  if (s <= b) return { x: TURN_X, y: BELT_A_Y + (s - a), alongX: false };
  return { x: TURN_X - (s - b), y: BELT_B_Y, alongX: true };
}

const sRowA = (x: number) => x - 1;
const sRowB = (x: number) => SEG[0]! + SEG[1]! + (TURN_X - x);

/** Где на ленте участок принимает и отдаёт кузов. */
export const STATIONS: Record<string, { entry: number; exit: number; row: "A" | "B" }> = {
  WELD: { entry: sRowA(8.6), exit: sRowA(17), row: "A" },
  PAINT: { entry: sRowA(19), exit: sRowA(29), row: "A" },
  ASSY: { entry: sRowB(29.4), exit: sRowB(14.6), row: "B" },
  QC: { entry: sRowB(12.4), exit: sRowB(6.6), row: "B" },
};

/** Буферы перед участками: отрезок ленты, где ждут кузова. */
export const BUFFERS: Record<string, { from: number; to: number; row: "A" | "B" | "turn" }> = {
  PAINT: { from: STATIONS.WELD!.exit + 0.4, to: STATIONS.PAINT!.entry - 0.2, row: "A" },
  ASSY: { from: STATIONS.PAINT!.exit + 0.6, to: STATIONS.ASSY!.entry - 0.2, row: "turn" },
  QC: { from: STATIONS.ASSY!.exit + 0.4, to: STATIONS.QC!.entry - 0.2, row: "B" },
};

export type Kind = "robot" | "booth" | "oven" | "conveyor" | "stand_gate" | "stand_box";

export interface Placement {
  id: string;
  kind: Kind;
  x: number;
  y: number;
  w: number;
  d: number;
  h: number;
  /** Сторона относительно ленты: дальняя рисуется до кузовов, ближняя — после. */
  side: "far" | "near" | "over";
}

export const PLACEMENTS: Placement[] = [
  // Сварка: четыре робота ABB по обе стороны ленты
  { id: "ABB-01", kind: "robot", x: 9.6, y: 1.9, w: 1.2, d: 1.2, h: 1.8, side: "far" },
  { id: "ABB-03", kind: "robot", x: 13.6, y: 1.9, w: 1.2, d: 1.2, h: 1.8, side: "far" },
  { id: "ABB-02", kind: "robot", x: 9.6, y: 6.0, w: 1.2, d: 1.2, h: 1.8, side: "near" },
  { id: "ABB-04", kind: "robot", x: 13.6, y: 6.0, w: 1.2, d: 1.2, h: 1.8, side: "near" },
  // Окраска: две камеры над лентой и печь сушки
  { id: "CAM-01", kind: "booth", x: 19.6, y: 2.6, w: 3.0, d: 3.8, h: 2.3, side: "over" },
  { id: "CAM-02", kind: "booth", x: 23.1, y: 2.6, w: 3.0, d: 3.8, h: 2.3, side: "over" },
  { id: "OVEN-01", kind: "oven", x: 26.6, y: 2.8, w: 2.4, d: 3.4, h: 2.0, side: "over" },
  // Сборка: три участка конвейера (привод — у начала каждого участка)
  { id: "CONV-01", kind: "conveyor", x: 24.6, y: 15.4, w: 4.8, d: 1.0, h: 0.8, side: "far" },
  { id: "CONV-02", kind: "conveyor", x: 19.6, y: 15.4, w: 4.8, d: 1.0, h: 0.8, side: "far" },
  { id: "CONV-03", kind: "conveyor", x: 14.6, y: 15.4, w: 4.8, d: 1.0, h: 0.8, side: "far" },
  // Контроль качества: рамка геометрии над лентой и камера герметичности
  { id: "QC-01", kind: "stand_gate", x: 10.4, y: 16.4, w: 1.4, d: 2.2, h: 2.0, side: "over" },
  { id: "QC-02", kind: "stand_box", x: 7.0, y: 16.3, w: 2.0, d: 2.4, h: 1.9, side: "over" },
];

/** Сегменты конвейера сборки — подсветка ленты под каждым конвейером. */
export const CONVEYOR_SPANS: Record<string, [number, number]> = {
  "CONV-01": [24.4, 29.6],
  "CONV-02": [19.4, 24.4],
  "CONV-03": [14.2, 19.4],
};
