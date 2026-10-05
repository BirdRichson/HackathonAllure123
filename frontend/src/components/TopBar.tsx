import { api } from "../api/client";
import { hhmm, longDate } from "../format";
import { useLive } from "../store/live";
import { TABS, useUi } from "../store/ui";

export function SpeedControl() {
  const status = useLive((s) => s.status);
  if (!status) return null;
  return (
    <div className="flex items-center gap-1" role="group" aria-label="Скорость времени завода">
      <button
        type="button"
        onClick={() => api.control({ paused: !status.paused })}
        className="flex h-8 w-8 items-center justify-center rounded-md border border-line bg-panel text-ink hover:bg-sunk"
        title={status.paused ? "Продолжить" : "Пауза"}
        aria-label={status.paused ? "Продолжить" : "Пауза"}
      >
        {status.paused ? "▶" : "❚❚"}
      </button>
      <div className="flex rounded-md border border-line bg-sunk p-0.5">
        {status.speeds.map((sp) => (
          <button
            key={sp}
            type="button"
            onClick={() => api.control({ speed: sp })}
            className={`rounded px-2 py-1 text-sm ${
              sp === status.speed ? "bg-panel font-semibold text-ink shadow-sm" : "text-muted hover:text-ink"
            }`}
            aria-pressed={sp === status.speed}
          >
            ×{sp}
          </button>
        ))}
      </div>
    </div>
  );
}

function AiStatus() {
  const ai = useLive((s) => s.ai);
  if (!ai) return null;
  const online = ai.llm_online;
  return (
    <div
      className="flex items-center gap-1.5 rounded-md border border-line px-2 py-1 text-sm"
      title={
        online
          ? `Языковая модель: ${ai.llm_label}. Прогноз отказов и разбор отчётов работают локально.`
          : "Языковая модель не подключена (нет ключа Groq/Gemini в .env). Прогнозы, разбор отчётов и выводы работают офлайн."
      }
    >
      <span className="rounded bg-[#efe9fb] px-1 text-[11px] font-semibold text-[#5b3fb0]">ИИ</span>
      <span className={online ? "text-ink" : "text-muted"}>{online ? (ai.llm_label ?? "").split(" · ")[0] : "офлайн"}</span>
      <span className="inline-block h-2 w-2 rounded-full" style={{ background: online ? "var(--color-ok)" : "var(--color-off)" }} />
    </div>
  );
}

export function TopBar() {
  const { status, shift, connection } = useLive();
  const { tab, setTab } = useUi();

  return (
    <header className="flex h-16 shrink-0 items-center gap-6 border-b border-line bg-panel px-5">
      <div className="flex items-center gap-3">
        <div className="cond flex h-9 items-center rounded-sm bg-signal px-2.5 text-lg font-semibold tracking-wide text-white">
          АЛЛЮР
        </div>
        <div className="leading-tight">
          <div className="text-[15px] font-semibold">Цифровой двойник завода</div>
          <div className="text-xs text-muted">Костанай, линии сварки, окраски и сборки</div>
        </div>
      </div>

      <nav className="flex h-full items-stretch gap-1" aria-label="Разделы">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={`border-b-[3px] px-3 text-[15px] ${
              tab === t.id ? "border-signal font-semibold text-ink" : "border-transparent text-muted hover:text-ink"
            }`}
            aria-current={tab === t.id ? "page" : undefined}
          >
            {t.label}
          </button>
        ))}
      </nav>

      <div className="ml-auto flex items-center gap-5">
        <AiStatus />
        {status && shift && (
          <div className="flex items-center gap-3">
            <div className="cond text-[34px] leading-none font-semibold">{hhmm(status.sim_time)}</div>
            <div className="text-sm leading-tight">
              <div className="font-medium">
                {shift.in_shift ? `Смена ${shift.id}, до ${hhmm(shift.end)}` : "Вне смены"}
              </div>
              <div className="text-muted">{longDate(status.sim_time)}</div>
            </div>
          </div>
        )}
        <SpeedControl />
        <div className="flex flex-col items-end text-xs leading-tight">
          <span className="rounded border border-warn px-1.5 py-0.5 font-medium text-warn" title="Данные модели, откалиброванной по тестовым данным организаторов">
            Демо-данные
          </span>
          <span className="mt-1 flex items-center gap-1 text-muted">
            <span
              className="inline-block h-2 w-2 rounded-full"
              style={{ background: connection === "online" ? "var(--color-ok)" : "var(--color-bad)" }}
              aria-hidden
            />
            {connection === "online" ? "Поток данных идёт" : connection === "offline" ? "Нет связи" : "Подключение"}
          </span>
        </div>
      </div>
    </header>
  );
}
