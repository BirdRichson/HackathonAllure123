import { useEffect } from "react";

import { DemoPanel } from "./components/DemoPanel";
import { TopBar } from "./components/TopBar";
import { AreaPanel } from "./pages/AreaPanel";
import { DataPage } from "./pages/DataPage";
import { DowntimePage } from "./pages/DowntimePage";
import { ForecastPage } from "./pages/ForecastPage";
import { MonitoringPage } from "./pages/MonitoringPage";
import { PlantPage } from "./pages/PlantPage";
import { initLive, useLive } from "./store/live";
import { useUi } from "./store/ui";

export default function App() {
  const tab = useUi((s) => s.tab);
  const connection = useLive((s) => s.connection);
  const ready = useLive((s) => s.kpi !== null);

  useEffect(() => {
    void initLive();
  }, []);

  return (
    <div className="flex h-full min-h-[760px] min-w-[1280px] flex-col">
      <TopBar />
      {connection === "offline" && (
        <div className="border-b border-line bg-[#fbe2df] px-5 py-2 text-sm text-bad">
          Нет связи с сервером. Запустите его командой <b>make dev</b> или <b>make demo</b> — интерфейс подключится сам.
        </div>
      )}
      {!ready ? (
        <div className="flex flex-1 items-center justify-center text-muted">Подключаюсь к заводу…</div>
      ) : (
        <>
          {tab === "plant" && <PlantPage />}
          {tab === "monitoring" && <MonitoringPage />}
          {tab === "forecast" && <ForecastPage />}
          {tab === "downtime" && <DowntimePage />}
          {tab === "data" && <DataPage />}
          <AreaPanel />
        </>
      )}
      <DemoPanel />
    </div>
  );
}
