import type { ReactNode } from "react";

import { type Box, P, faces, leftFaceRect, pts, shade } from "./iso";

/** Коробка с тремя видимыми гранями. Свет падает слева сверху: правая грань темнее. */
export function IsoBox({ box, color, stroke, onClick }: { box: Box; color: string; stroke?: string; onClick?: () => void }) {
  const f = faces(box);
  const s = stroke ?? shade(color, -0.32);
  return (
    <g onClick={onClick}>
      <polygon points={f.left} fill={shade(color, -0.1)} stroke={s} strokeWidth={0.6} strokeLinejoin="round" />
      <polygon points={f.right} fill={shade(color, -0.22)} stroke={s} strokeWidth={0.6} strokeLinejoin="round" />
      <polygon points={f.top} fill={color} stroke={s} strokeWidth={0.6} strokeLinejoin="round" />
    </g>
  );
}

const ORANGE = "#ef8a14";
const STEEL = "#4a5662";
const WHITE = "#fbfcfd";
const GLASS = "#b7d3ee";

export function Robot({ x, y, side }: { x: number; y: number; side: "far" | "near" | "over" }) {
  // Основание, поворотная колонна и плечо, вытянутое к ленте.
  const toBelt = side === "far" ? 1 : -1;
  const armY = side === "far" ? y + 0.45 : y - 0.75;
  return (
    <g>
      <IsoBox box={{ x, y, w: 1.2, d: 1.2, h: 0.32 }} color={STEEL} />
      <IsoBox box={{ x: x + 0.3, y: y + 0.3, z: 0.32, w: 0.6, d: 0.6, h: 0.85 }} color={ORANGE} />
      <IsoBox box={{ x: x + 0.38, y: armY, z: 1.17, w: 0.44, d: 1.5, h: 0.3 }} color={ORANGE} />
      <IsoBox
        box={{ x: x + 0.45, y: side === "far" ? y + 1.75 : y - 0.85, z: 0.75 + 0.02 * toBelt, w: 0.3, d: 0.3, h: 0.45 }}
        color="#6c7884"
      />
    </g>
  );
}

export function Booth({ x, y, w, d, h }: { x: number; y: number; w: number; d: number; h: number }) {
  return (
    <g>
      <IsoBox box={{ x, y, w, d, h }} color={WHITE} stroke="#aab4be" />
      {/* смотровое окно и полоса вытяжки */}
      <polygon points={leftFaceRect(x + 0.35, x + w - 0.35, y + d, 0.85, 1.6)} fill={GLASS} stroke="#8fb3d6" strokeWidth={0.6} />
      <IsoBox box={{ x: x + 0.5, y: y + 0.6, z: h, w: w - 1.0, d: 0.7, h: 0.28 }} color="#d7dde3" />
      <IsoBox box={{ x: x + 0.5, y: y + d - 1.3, z: h, w: w - 1.0, d: 0.7, h: 0.28 }} color="#d7dde3" />
    </g>
  );
}

export function Oven({ x, y, w, d, h }: { x: number; y: number; w: number; d: number; h: number }) {
  return (
    <g>
      <IsoBox box={{ x, y, w, d, h }} color="#cdd3d9" />
      <polygon points={leftFaceRect(x + 0.25, x + w - 0.25, y + d, 0.25, 0.55)} fill="#f2a24a" opacity={0.9} />
      <IsoBox box={{ x: x + w - 0.8, y: y + 0.4, z: h, w: 0.5, d: 0.5, h: 0.9 }} color="#9aa5b0" />
    </g>
  );
}

export function ConveyorDrive({ x, y, w }: { x: number; y: number; w: number }) {
  // Ограждение вдоль ленты и мотор-редуктор в начале участка.
  return (
    <g>
      <IsoBox box={{ x, y: y + 0.55, w, d: 0.18, h: 0.4 }} color="#dfe4e9" />
      <IsoBox box={{ x: x + w - 0.9, y, w: 0.8, d: 0.7, h: 0.75 }} color={STEEL} />
      <IsoBox box={{ x: x + w - 0.75, y: y + 0.12, z: 0.75, w: 0.5, d: 0.46, h: 0.18 }} color={ORANGE} />
    </g>
  );
}

export function StandGate({ x, y, w, d, h }: { x: number; y: number; w: number; d: number; h: number }) {
  // Рамка измерения геометрии: две стойки и балка над лентой.
  return (
    <g>
      <IsoBox box={{ x, y, w, d: 0.3, h }} color="#e6eaee" />
      <IsoBox box={{ x, y: y + d - 0.3, w, d: 0.3, h }} color="#e6eaee" />
      <IsoBox box={{ x, y, z: h - 0.3, w, d, h: 0.3 }} color={ORANGE} />
    </g>
  );
}

export function StandBox({ x, y, w, d, h }: { x: number; y: number; w: number; d: number; h: number }) {
  return (
    <g>
      <IsoBox box={{ x, y, w, d, h }} color="#eef1f4" stroke="#aab4be" />
      <polygon points={leftFaceRect(x + 0.3, x + w - 0.3, y + d, 0.7, 1.35)} fill={GLASS} stroke="#8fb3d6" strokeWidth={0.6} />
    </g>
  );
}

/** Стеллаж склада комплектующих с коробами. */
export function Rack({ x, y, w, filled }: { x: number; y: number; w: number; filled: number }) {
  const n = Math.max(1, Math.floor(w / 0.9));
  const boxes: ReactNode[] = [];
  for (let level = 0; level < 3; level++) {
    for (let i = 0; i < n; i++) {
      if ((level * n + i) / (3 * n) > filled) continue;
      boxes.push(
        <IsoBox
          key={`${level}-${i}`}
          box={{ x: x + 0.1 + i * 0.9, y: y + 0.12, z: 0.1 + level * 0.62, w: 0.72, d: 0.66, h: 0.45 }}
          color={level % 2 ? "#e9a35a" : "#d9c29e"}
        />,
      );
    }
  }
  return (
    <g>
      {[0, 0.62, 1.24].map((z) => (
        <IsoBox key={z} box={{ x, y, z, w, d: 0.9, h: 0.08 }} color="#b8c1ca" />
      ))}
      {boxes}
    </g>
  );
}

/** Кузов: корпус и кабина. Рисуется в начале координат плана, смещается transform-ом. */
export function BodyShape({ color, alongX }: { color: string; alongX: boolean }) {
  const L = 1.4;
  const W = 0.74;
  const box = alongX ? { w: L, d: W } : { w: W, d: L };
  const cab = alongX ? { x: -0.2, y: -W / 2 + 0.07, w: 0.68, d: W - 0.14 } : { x: -W / 2 + 0.07, y: -0.2, w: W - 0.14, d: 0.68 };
  return (
    <g>
      <IsoBox box={{ x: -box.w / 2, y: -box.d / 2, z: 0.25, ...box, h: 0.26 }} color={color} stroke={shade(color, -0.4)} />
      <IsoBox box={{ ...cab, z: 0.51, h: 0.2 }} color={shade(color, -0.06)} stroke={shade(color, -0.4)} />
    </g>
  );
}

export const translate = (x: number, y: number, z = 0) => {
  const [a, b] = P(x, y, z);
  return `translate(${a.toFixed(1)},${b.toFixed(1)})`;
};

export { pts };
