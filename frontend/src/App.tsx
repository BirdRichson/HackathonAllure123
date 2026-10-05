import { useEffect } from "react";

import { MonthPlanPanel } from "./components/MonthPlanPanel";
import { PlantFlow } from "./components/PlantFlow";
import { TargetsPanel } from "./components/TargetsPanel";
import { TopBar } from "./components/TopBar";
import { useAppStore } from "./store/useAppStore";

export default function App() {
  const { connection, plant, targets, load, pingHealth } = useAppStore();

  useEffect(() => {
    void load();
    const id = setInterval(() => void pingHealth(), 5000);
    return () => clearInterval(id);
  }, [load, pingHealth]);

  return (
    <div className="flex min-h-full flex-col">
      <TopBar />

      {connection === "offline" && (
        <div className="border-b border-line px-6 py-2 text-sm" style={{ color: "var(--color-bad)" }}>
          ✕ Сервер не отвечает. Запустите бэкенд: <code className="font-mono">make dev</code> или{" "}
          <code className="font-mono">docker compose up</code>.
        </div>
      )}

      <main className="flex flex-1 flex-col gap-6 p-6">
        {plant && (
          <section>
            <h2 className="mb-3 text-sm font-medium uppercase tracking-wider text-muted">Схема производства</h2>
            <PlantFlow plant={plant} />
          </section>
        )}

        {plant && targets && (
          <section className="grid grid-cols-[2fr_1fr] gap-6">
            <div>
              <h2 className="mb-3 text-sm font-medium uppercase tracking-wider text-muted">Целевые показатели</h2>
              <TargetsPanel targets={targets} />
            </div>
            <div>
              <h2 className="mb-3 text-sm font-medium uppercase tracking-wider text-muted">План</h2>
              <MonthPlanPanel plant={plant} targets={targets} />
            </div>
          </section>
        )}

        <p className="mt-auto text-sm text-muted">
          Этап 0 — каркас. Состояния оборудования, KPI в реальном времени и прогнозы появятся на следующих этапах.
        </p>
      </main>
    </div>
  );
}
