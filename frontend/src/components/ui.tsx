import type { ReactNode } from "react";

import { SEVERITY, STATE } from "../theme/states";
import type { Severity, State } from "../types";

export function StateChip({ state, text, size = "md" }: { state: State; text?: string; size?: "sm" | "md" }) {
  const s = STATE[state];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full font-medium whitespace-nowrap ${
        size === "sm" ? "px-2 py-0.5 text-xs" : "px-2.5 py-1 text-sm"
      }`}
      style={{ background: s.tint, color: s.color }}
      title={text || s.label}
    >
      <span aria-hidden>{s.icon}</span>
      {s.label}
    </span>
  );
}

export function SeverityMark({ severity }: { severity: Severity }) {
  const s = SEVERITY[severity];
  return (
    <span className="inline-flex items-center gap-1 text-xs font-medium" style={{ color: s.color }}>
      <span className="inline-block h-2 w-2 rounded-full" style={{ background: s.color }} aria-hidden />
      {s.label}
    </span>
  );
}

/** Раздел панели: заголовок обычным регистром и содержимое. */
export function Section({
  title,
  aside,
  children,
  className = "",
}: {
  title: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`flex min-h-0 flex-col ${className}`}>
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <h2 className="cond text-[17px] font-semibold text-ink">{title}</h2>
        {aside && <div className="text-sm text-muted">{aside}</div>}
      </div>
      {children}
    </section>
  );
}

/**
 * Шкала значения против цели: заполнение, отметка цели и подпись.
 * `invert` — для показателей, где меньше лучше (брак).
 */
export function TargetBar({
  value,
  target,
  max = 1,
  invert = false,
  color,
}: {
  value: number;
  target: number;
  max?: number;
  invert?: boolean;
  color?: string;
}) {
  const ok = invert ? value <= target : value >= target;
  const fill = color ?? (ok ? "var(--color-ok)" : "var(--color-bad)");
  return (
    <div className="relative h-2 w-full rounded-full bg-sunk">
      <div
        className="absolute inset-y-0 left-0 rounded-full"
        style={{ width: `${Math.min(100, (value / max) * 100)}%`, background: fill }}
      />
      <div
        className="absolute -top-1 -bottom-1 w-0.5 bg-ink"
        style={{ left: `${Math.min(100, (target / max) * 100)}%` }}
        title="Цель"
      />
    </div>
  );
}

/** Шкала «до планового ТО»: заполняется по мере наработки, краснеет у срока. */
export function MaintenanceBar({ progress, due }: { progress: number; due: boolean }) {
  const color = due || progress >= 0.95 ? "var(--color-bad)" : progress >= 0.8 ? "var(--color-warn)" : "var(--color-info)";
  return (
    <div className="h-1.5 w-full rounded-full bg-sunk" aria-hidden>
      <div className="h-full rounded-full" style={{ width: `${Math.min(100, progress * 100)}%`, background: color }} />
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-md bg-sunk px-3 py-4 text-sm text-muted">{children}</div>;
}
