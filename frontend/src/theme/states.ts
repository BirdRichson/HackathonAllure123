import type { Severity, State } from "../types";

/** Единое оформление состояний: цвет никогда не единственный носитель смысла — рядом подпись и значок. */
export const STATE: Record<State, { label: string; color: string; tint: string; icon: string }> = {
  running: { label: "Работает", color: "var(--color-ok)", tint: "#e3f4ea", icon: "▶" },
  starved: { label: "Нет входа", color: "var(--color-warn)", tint: "#fbf1d9", icon: "◇" },
  blocked: { label: "Выход занят", color: "var(--color-warn)", tint: "#fbf1d9", icon: "■" },
  idle: { label: "Ожидание", color: "var(--color-warn)", tint: "#fbf1d9", icon: "‖" },
  down: { label: "Авария", color: "var(--color-bad)", tint: "#fbe2df", icon: "✕" },
  maintenance: { label: "ТО", color: "var(--color-info)", tint: "#e2ebfa", icon: "⚙" },
  setup: { label: "Переналадка", color: "var(--color-info)", tint: "#e2ebfa", icon: "↻" },
  offline: { label: "Вне смены", color: "var(--color-off)", tint: "#eceff2", icon: "○" },
};

/** Тот же набор в hex — для SVG карты и графиков, где CSS-переменные неудобны. */
export const HEX: Record<State, string> = {
  running: "#17924f",
  starved: "#d59a12",
  blocked: "#d59a12",
  idle: "#d59a12",
  down: "#d2352b",
  maintenance: "#2c67cc",
  setup: "#2c67cc",
  offline: "#8a949f",
};

export const SEVERITY: Record<Severity, { label: string; color: string }> = {
  critical: { label: "Критично", color: "var(--color-bad)" },
  warning: { label: "Внимание", color: "var(--color-warn)" },
  info: { label: "К сведению", color: "var(--color-info)" },
};

export const LEVEL_COLOR = { ok: "var(--color-ok)", warn: "var(--color-warn)", bad: "var(--color-bad)" } as const;

/** Цвета кузовов: до окраски — металл, после — цвет модели. */
export const BODY = {
  metal: "#a3acb6",
  models: {
    "Chevrolet Onix": "#c2c9d2",
    "Chevrolet Cobalt": "#fbfbfc",
    "JAC J7": "#4f78b3",
  } as Record<string, string>,
};
