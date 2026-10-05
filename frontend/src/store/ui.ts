import { create } from "zustand";

export type Tab = "plant" | "monitoring" | "forecast" | "downtime" | "data";

export const TABS: { id: Tab; label: string }[] = [
  { id: "plant", label: "Завод" },
  { id: "monitoring", label: "Мониторинг" },
  { id: "forecast", label: "Прогноз" },
  { id: "downtime", label: "Простои" },
  { id: "data", label: "Данные завода" },
];

interface UiState {
  tab: Tab;
  openArea: string | null;
  selectedEq: string | null;
  demoPanel: boolean;
  reportFor: { equipment: string; reportId?: string } | null; // для какой остановки открыта форма отчёта
  setTab: (t: Tab) => void;
  openAreaPanel: (area: string, eq?: string | null) => void;
  closeArea: () => void;
  selectEq: (eq: string | null) => void;
  toggleDemo: () => void;
  startReport: (eq: string | null, reportId?: string) => void;
}

function readHash(): { tab: Tab; area: string | null } {
  const [, tab, area] = location.hash.split("/");
  const valid = TABS.some((t) => t.id === tab);
  return { tab: valid ? (tab as Tab) : "plant", area: area || null };
}

function writeHash(tab: Tab, area: string | null) {
  const h = `#/${tab}${area ? `/${area}` : ""}`;
  if (location.hash !== h) history.replaceState(null, "", h);
}

const initial = readHash();

export const useUi = create<UiState>((set, get) => ({
  tab: initial.tab,
  openArea: initial.area,
  selectedEq: null,
  demoPanel: false,
  reportFor: null,
  setTab: (tab) => {
    set({ tab, openArea: null });
    writeHash(tab, null);
  },
  openAreaPanel: (area, eq = null) => {
    set({ openArea: area, selectedEq: eq, tab: "plant" });
    writeHash("plant", area);
  },
  closeArea: () => {
    set({ openArea: null, selectedEq: null });
    writeHash(get().tab, null);
  },
  selectEq: (eq) => set({ selectedEq: eq }),
  toggleDemo: () => set((s) => ({ demoPanel: !s.demoPanel })),
  startReport: (eq, reportId) => {
    set({ reportFor: eq ? { equipment: eq, reportId } : null, tab: "downtime", openArea: null });
    writeHash("downtime", null);
  },
}));
