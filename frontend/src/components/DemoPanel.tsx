import { useEffect, useState } from "react";

import { api } from "../api/client";
import { usePoll } from "../hooks/usePoll";
import { useUi } from "../store/ui";
import { SpeedControl } from "./TopBar";

/** Скрытая панель ведущего демо: клавиша D. Скорость, пауза, сброс к началу. */
export function DemoPanel() {
  const { demoPanel, toggleDemo } = useUi();
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const { data: scenarios } = usePoll(() => api.scenarios(), [], 600000);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      if (e.key === "d" || e.key === "D" || e.key === "в" || e.key === "В") toggleDemo();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggleDemo]);

  if (!demoPanel) return null;
  return (
    <div className="slide-in fixed bottom-4 left-4 z-50 w-[340px] rounded-lg border border-line bg-panel p-4 shadow-lg">
      <div className="mb-3 flex items-center justify-between">
        <div className="cond text-lg font-semibold">Пульт демо</div>
        <button type="button" onClick={toggleDemo} className="text-sm text-muted hover:text-ink">
          Скрыть (D)
        </button>
      </div>
      <div className="mb-3">
        <SpeedControl />
      </div>
      <button
        type="button"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          try {
            await api.control({ reset: true });
          } finally {
            setBusy(false);
          }
        }}
        className="w-full rounded-md border border-line bg-sunk px-3 py-2 text-left text-sm font-medium hover:bg-line disabled:opacity-60"
      >
        {busy ? "Сбрасываю…" : "Сбросить демо к 10:30"}
      </button>
      <div className="mt-4 mb-2 text-sm font-semibold">Сценарии</div>
      <div className="flex flex-col gap-2">
        {Object.entries(scenarios ?? {}).map(([name, sc]) => (
          <button
            key={name}
            type="button"
            title={sc.details}
            onClick={async () => {
              const r = await api.trigger(name);
              setNote(`Запущено: ${r.title}`);
            }}
            className="rounded-md border border-line px-3 py-2 text-left text-sm hover:bg-sunk"
          >
            <div className="font-medium">{sc.title}</div>
            <div className="text-xs text-muted">{sc.details}</div>
          </button>
        ))}
      </div>
      {note && <p className="mt-2 text-xs text-ok">{note}</p>}
    </div>
  );
}
