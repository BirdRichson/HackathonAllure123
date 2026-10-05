import { useEffect, useState } from "react";

import { useAppStore } from "../store/useAppStore";
import type { Shift } from "../types";

const PLANT_OFFSET_MS = 5 * 3600 * 1000; // Костанай, UTC+5

function plantNow(): Date {
  // Сдвигаем на UTC+5 и дальше читаем через getUTC*, чтобы не зависеть от часового пояса ноутбука.
  return new Date(Date.now() + PLANT_OFFSET_MS);
}

function toMinutes(hhmm: string): number {
  const [h = "0", m = "0"] = hhmm.split(":");
  const total = Number(h) * 60 + Number(m);
  return total === 0 ? 24 * 60 : total;
}

function currentShift(shifts: Shift[], now: Date): Shift | null {
  const minutes = now.getUTCHours() * 60 + now.getUTCMinutes();
  return (
    shifts.find((s) => {
      const start = toMinutes(s.start) % (24 * 60);
      return minutes >= start && minutes < toMinutes(s.end);
    }) ?? null
  );
}

const pad = (n: number) => String(n).padStart(2, "0");

export function TopBar() {
  const { connection, health, plant } = useAppStore();
  const [now, setNow] = useState(plantNow);

  useEffect(() => {
    const id = setInterval(() => setNow(plantNow()), 1000);
    return () => clearInterval(id);
  }, []);

  const shift = plant ? currentShift(plant.schedule.shifts, now) : null;
  const time = `${pad(now.getUTCHours())}:${pad(now.getUTCMinutes())}:${pad(now.getUTCSeconds())}`;
  const date = `${pad(now.getUTCDate())}.${pad(now.getUTCMonth() + 1)}.${now.getUTCFullYear()}`;
  const isDemo = (health?.data_mode ?? "demo") === "demo";

  return (
    <header className="flex items-center justify-between gap-6 border-b border-line bg-panel px-6 py-3">
      <div className="flex items-center gap-3">
        <div className="h-8 w-8 rounded-sm bg-accent" aria-hidden />
        <div>
          <div className="text-lg font-semibold tracking-wide">АЛЛЮР</div>
          <div className="text-sm text-muted">Цифровой двойник завода</div>
        </div>
      </div>

      <div className="flex items-center gap-6">
        <div className="text-right">
          <div className="font-mono text-3xl leading-none">{time}</div>
          <div className="mt-1 text-sm text-muted">{date} · Костанай, UTC+5</div>
        </div>
        <div className="rounded border border-line bg-panel-2 px-3 py-2 text-sm">
          {shift ? (
            <>
              <span className="font-semibold">Смена {shift.id}</span>
              <span className="text-muted">
                {" "}
                · {shift.start}–{shift.end}
              </span>
            </>
          ) : (
            <span className="text-muted">Вне смены</span>
          )}
        </div>
      </div>

      <div className="flex items-center gap-3 text-sm">
        <span
          className="rounded border px-3 py-1.5 font-medium"
          style={{
            borderColor: isDemo ? "var(--color-warn)" : "var(--color-ok)",
            color: isDemo ? "var(--color-warn)" : "var(--color-ok)",
          }}
        >
          {isDemo ? "Демо-данные" : "Данные завода"}
        </span>
        <span className="flex items-center gap-2 text-muted">
          <span
            className="inline-block h-2.5 w-2.5 rounded-full"
            style={{
              background:
                connection === "online"
                  ? "var(--color-ok)"
                  : connection === "offline"
                    ? "var(--color-bad)"
                    : "var(--color-off)",
            }}
            aria-hidden
          />
          {connection === "online" ? "Сервер на связи" : connection === "offline" ? "Нет связи с сервером" : "Подключение…"}
        </span>
      </div>
    </header>
  );
}
