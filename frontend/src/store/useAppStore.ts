import { create } from "zustand";

import { api } from "../api/client";
import type { Health, Plant, Targets } from "../types";

type Connection = "connecting" | "online" | "offline";

interface AppState {
  connection: Connection;
  health: Health | null;
  plant: Plant | null;
  targets: Targets | null;
  load: () => Promise<void>;
  pingHealth: () => Promise<void>;
}

export const useAppStore = create<AppState>((set, get) => ({
  connection: "connecting",
  health: null,
  plant: null,
  targets: null,

  load: async () => {
    try {
      const [health, plant, targets] = await Promise.all([api.health(), api.plant(), api.targets()]);
      set({ health, plant, targets, connection: "online" });
    } catch {
      set({ connection: "offline" });
    }
  },

  pingHealth: async () => {
    try {
      const health = await api.health();
      const wasOffline = get().connection !== "online";
      set({ health, connection: "online" });
      if (wasOffline && !get().plant) await get().load();
    } catch {
      set({ connection: "offline" });
    }
  },
}));
