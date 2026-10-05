import { useRef, useState } from "react";

import { api } from "../api/client";
import { Empty, Section, SeverityMark } from "../components/ui";
import { ddmm, int, num, pct } from "../format";
import { usePoll } from "../hooks/usePoll";
import { SEVERITY } from "../theme/states";
import type { ImportResult } from "../types";

function Findings({ data }: { data: ImportResult }) {
  return (
    <ul className="grid grid-cols-2 gap-3">
      {data.findings.map((f, i) => (
        <li
          key={i}
          className="rounded-md border border-line bg-panel p-4"
          style={{ borderLeft: `4px solid ${SEVERITY[f.severity].color}` }}
        >
          <SeverityMark severity={f.severity} />
          <div className="cond mt-1 text-lg leading-snug font-semibold">{f.title}</div>
          <div className="mt-1 text-sm text-muted">{f.details}</div>
        </li>
      ))}
    </ul>
  );
}

function KpiTable({ data }: { data: ImportResult }) {
  const t = data.targets;
  return (
    <table className="w-full text-sm">
      <thead className="text-left text-muted">
        <tr>
          {["Дата", "Линия", "План", "Факт", "Время работы", "Загрузка", "Доступн.", "Производит.", "Качество", "OEE", "Брак"].map((h) => (
            <th key={h} className="pb-2 pr-2 font-normal">
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {data.kpi_rows.map((r) => (
          <tr key={`${r.date}${r.line_id}`} className="border-t border-line">
            <td className="py-2 pr-2">{ddmm(r.date)}</td>
            <td className="py-2 pr-2 font-medium">{r.line_id}</td>
            <td className="py-2 pr-2">{int(r.plan_units as number)}</td>
            <td className="py-2 pr-2">{int(r.fact_units as number)}</td>
            <td className="py-2 pr-2">{num(r.run_hours as number, 1)} ч</td>
            <td className="py-2 pr-2">{int(r.load_pct as number)}%</td>
            <td className="py-2 pr-2">{pct(r.availability)}</td>
            <td className="py-2 pr-2">{pct(r.performance)}</td>
            <td className="py-2 pr-2">{pct(r.quality)}</td>
            <td className="py-2 pr-2 font-semibold" style={{ color: r.oee < t.oee_min + 0.01 ? "var(--color-warn)" : "var(--color-ok)" }}>
              {pct(r.oee)}
            </td>
            <td className="py-2 pr-2 font-semibold" style={{ color: r.defect_rate > t.defect_rate_max ? "var(--color-bad)" : undefined }}>
              {pct(r.defect_rate)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function DowntimeTable({ data }: { data: ImportResult }) {
  const rows = data.tables.downtime ?? [];
  return (
    <table className="w-full text-sm">
      <thead className="text-left text-muted">
        <tr>
          {["Дата", "Участок", "Оборудование", "Причина", "Длительность"].map((h) => (
            <th key={h} className="pb-2 pr-2 font-normal">
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i} className="border-t border-line">
            <td className="py-2 pr-2">{ddmm(String(r.date))}</td>
            <td className="py-2 pr-2">{r.area}</td>
            <td className="py-2 pr-2 font-medium">{r.equipment}</td>
            <td className="py-2 pr-2">{r.reason_text}</td>
            <td className="py-2 pr-2">{int(r.duration_min as number)} мин</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function PlanModels({ data }: { data: ImportResult }) {
  const rows = (data.tables.plan_models ?? []) as { model: string; plan_month_units: number }[];
  const goal = data.targets.monthly_output_min;
  const total = rows.reduce((a, r) => a + r.plan_month_units, 0);
  return (
    <div>
      <div className="flex h-8 w-full overflow-hidden rounded-md bg-sunk">
        {rows.map((r, i) => (
          <div
            key={r.model}
            className="flex items-center justify-center text-xs font-medium text-white"
            style={{ width: `${(r.plan_month_units / goal) * 100}%`, background: ["#3d4955", "#6b7a89", "#9aa6b2"][i % 3] }}
            title={`${r.model}: ${int(r.plan_month_units)}`}
          >
            {r.model.replace("Chevrolet ", "")}
          </div>
        ))}
        {total < goal && (
          <div className="flex flex-1 items-center justify-center text-xs font-semibold text-bad">−{int(goal - total)}</div>
        )}
      </div>
      <div className="mt-2 flex justify-between text-sm text-muted">
        <span>По моделям: {int(total)}</span>
        <span>Цель: {int(goal)} в месяц</span>
      </div>
    </div>
  );
}

export function DataPage() {
  const [version, setVersion] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const { data } = usePoll(() => api.latestImport(), [version], 60000);

  const onFiles = async (files: FileList | null) => {
    if (!files?.length) return;
    setUploading(true);
    setError(null);
    try {
      await api.upload(files);
      setVersion((v) => v + 1);
    } catch (e) {
      setError(`Файл не загружен: ${(e as Error).message}`);
    } finally {
      setUploading(false);
      if (input.current) input.current.value = "";
    }
  };

  return (
    <div className="scroll-thin min-h-0 flex-1 overflow-y-auto p-4">
      <div className="mx-auto flex max-w-[1500px] flex-col gap-4">
        <div className="flex items-end justify-between gap-6 rounded-lg bg-panel p-5">
          <div>
            <h1 className="cond text-[28px] font-semibold">Данные завода</h1>
            <p className="mt-1 max-w-[760px] text-muted">
              Двойник читает выгрузку в формате организаторов (docx, xlsx или csv), считает OEE по каждой смене и сразу показывает,
              где завод выходит за свои цели.
            </p>
            {data && (
              <p className="mt-2 text-sm text-muted">
                Загружено: {data.files.join(", ")}. Строк: линии {data.rows.lines ?? 0}, простои {data.rows.downtime ?? 0}, план{" "}
                {data.rows.plan_models ?? 0}, качество {data.rows.quality ?? 0}.
              </p>
            )}
          </div>
          <div className="text-right">
            <input
              ref={input}
              type="file"
              accept=".docx,.xlsx,.xls,.csv"
              multiple
              className="hidden"
              onChange={(e) => onFiles(e.target.files)}
            />
            <button
              type="button"
              onClick={() => input.current?.click()}
              disabled={uploading}
              className="rounded-md bg-signal px-5 py-2.5 font-semibold text-white hover:brightness-95 disabled:opacity-50"
            >
              {uploading ? "Загружаю…" : "Загрузить файл"}
            </button>
            {error && <div className="mt-2 max-w-[360px] text-sm text-bad">{error}</div>}
          </div>
        </div>

        {!data ? (
          <Empty>Данные завода ещё не загружались. Нажмите «Загрузить файл».</Empty>
        ) : (
          <>
            <div className="rounded-lg bg-panel p-5">
              <Section title="Что двойник нашёл в данных" aside={`${data.findings.length} наблюдений`}>
                <Findings data={data} />
              </Section>
            </div>
            <div className="grid grid-cols-[1.6fr_1fr] gap-4">
              <div className="rounded-lg bg-panel p-5">
                <Section title="Смены по линиям" aside="одна строка — смена 8 ч, идеальный цикл 3,8 мин">
                  <KpiTable data={data} />
                </Section>
              </div>
              <div className="flex flex-col gap-4">
                <div className="rounded-lg bg-panel p-5">
                  <Section title="Месячный план по моделям">
                    <PlanModels data={data} />
                  </Section>
                </div>
                <div className="rounded-lg bg-panel p-5">
                  <Section title="Простои оборудования">
                    <DowntimeTable data={data} />
                  </Section>
                </div>
              </div>
            </div>
            {data.warnings.length > 0 && (
              <div className="rounded-lg bg-panel p-5">
                <Section title="Замечания к исходным данным">
                  <ul className="list-disc pl-5 text-sm text-muted">
                    {data.warnings.map((w) => (
                      <li key={w}>{w}</li>
                    ))}
                  </ul>
                </Section>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
