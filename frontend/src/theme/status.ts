/** Состояния оборудования и их единое оформление (цвет + подпись + значок). Цвет никогда не единственный носитель смысла. */
export type EquipmentState =
  | "running"
  | "starved"
  | "blocked"
  | "down"
  | "maintenance"
  | "setup"
  | "offline";

export const STATE_META: Record<EquipmentState, { label: string; color: string; icon: string }> = {
  running: { label: "Работает", color: "var(--color-ok)", icon: "▶" },
  starved: { label: "Нет входа", color: "var(--color-warn)", icon: "◇" },
  blocked: { label: "Выход занят", color: "var(--color-warn)", icon: "■" },
  down: { label: "Авария", color: "var(--color-bad)", icon: "✕" },
  maintenance: { label: "ТО", color: "var(--color-info)", icon: "⚙" },
  setup: { label: "Переналадка", color: "var(--color-info)", icon: "↻" },
  offline: { label: "Отключено", color: "var(--color-off)", icon: "○" },
};
