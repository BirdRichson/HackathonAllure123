import { useEffect, useMemo, useState } from "react";

import { api } from "../api/client";
import { AiTag } from "../components/ai";
import { Section, StateChip } from "../components/ui";
import { dateTime, diffMin, hhmm, minutes, pct } from "../format";
import { usePoll } from "../hooks/usePoll";
import { useLive } from "../store/live";
import { useUi } from "../store/ui";
import type { Report, Suggestion } from "../types";
import { SUBTYPE_TEXT } from "./AreaPanel";

/** Подсказка ИИ, пока рабочий пишет: что случилось по тексту и какую причину выбрать. */
function AiHint({
  eqId,
  description,
  actions,
  reason,
  onPick,
}: {
  eqId: string | null;
  description: string;
  actions: string;
  reason: string | null;
  onPick: (code: string) => void;
}) {
  const llmOnline = useLive((s) => s.ai?.llm_online ?? false);
  const [hint, setHint] = useState<Suggestion | null>(null);
  const [llmBusy, setLlmBusy] = useState(false);
  const text = description.trim();

  useEffect(() => {
    if (!eqId || text.length < 6) {
      setHint(null);
      return;
    }
    const id = setTimeout(() => {
      api
        .suggest({ equipment_id: eqId, description: text, actions_taken: actions, reason })
        .then(setHint)
        .catch(() => {});
    }, 350);
    return () => clearTimeout(id);
  }, [eqId, text, actions, reason]);

  if (!hint?.prediction) return null;
  const p = hint.prediction;
  const askLlm = async () => {
    if (!eqId) return;
    setLlmBusy(true);
    try {
      setHint(await api.suggest({ equipment_id: eqId, description: text, actions_taken: actions, reason, use_llm: true }));
    } finally {
      setLlmBusy(false);
    }
  };
  return (
    <div className={`mt-2 rounded-md px-3 py-2 text-sm ${hint.mismatch ? "bg-[#fbe2df]" : "bg-[#f4f1fc]"}`}>
      <div className="flex flex-wrap items-center gap-2">
        <AiTag title={p.source === "llm" ? "Разобрала языковая модель" : "Локальная модель, работает без сети"} />
        <span>
          По описанию — <b>{SUBTYPE_TEXT[p.subtype] ?? p.subtype}</b>
          {p.component ? ` (${p.component})` : ""}, причина «{p.reason_label}», уверенность {pct(p.confidence, 0)}
        </span>
        {reason !== p.reason && (
          <button type="button" onClick={() => onPick(p.reason)} className="rounded border border-ink bg-panel px-2 py-0.5 text-xs font-medium hover:bg-sunk">
            Выбрать «{p.reason_label}»
          </button>
        )}
        {llmOnline && p.source !== "llm" && (
          <button type="button" disabled={llmBusy} onClick={() => void askLlm()} className="text-xs text-info hover:underline disabled:opacity-50">
            {llmBusy ? "LLM разбирает…" : "уточнить у LLM"}
          </button>
        )}
      </div>
      {hint.mismatch && <div className="mt-1 font-medium text-bad">Выбранная причина не совпадает с описанием — проверьте, пожалуйста.</div>}
      {p.note && <div className="mt-1 text-ink">Совет: {p.note}</div>}
      {hint.llm_error && <div className="mt-1 text-xs text-muted">LLM недоступна, показан ответ локальной модели.</div>}
    </div>
  );
}

function AnalysisStrip({ area, seq }: { area: string; seq: number }) {
  const { data: a } = usePoll(() => api.reportsAnalysis(area || undefined), [area, seq], 15000);
  if (!a || !a.total) return null;
  const rec = a.recurring[0];
  return (
    <div className="mb-3 flex flex-wrap items-center gap-x-5 gap-y-1 rounded-md bg-[#f4f1fc] px-3 py-2 text-sm">
      <AiTag title="Сводка ИИ по отчётам за 30 дней" />
      <span>
        Не заполнено: <b>{a.drafts}</b> из {a.total}
      </span>
      <span>
        Причина, похоже, указана неверно: <b>{a.mismatches}</b> ({pct(a.mismatch_share, 0)})
      </span>
      {rec && (
        <span>
          Чаще всего: <b>{rec.name}</b> — {rec.subtype_label}, {rec.count} раз
          {rec.components[0] ? ` (${rec.components[0].name})` : ""}
        </span>
      )}
    </div>
  );
}

const AREAS: [string, string][] = [
  ["WELD", "Сварка"],
  ["PAINT", "Окраска"],
  ["ASSY", "Сборка"],
  ["QC", "Контроль качества"],
];

// Причины, которые выбирает рабочий (ожидание соседних участков система видит сама).
const FORM_REASONS = ["breakdown", "consumables", "planned_maintenance", "no_material", "changeover", "quality_hold", "operator", "other"];
const ROLES = ["оператор", "наладчик", "мастер"] as const;

function ReportForm({ reports, labels }: { reports: Report[]; labels: Record<string, string> }) {
  const equipment = useLive((s) => s.equipment);
  const simTime = useLive((s) => s.status?.sim_time ?? "");
  const { reportFor, startReport } = useUi();
  const [eqId, setEqId] = useState<string | null>(reportFor?.equipment ?? null);
  const [pinnedId, setPinnedId] = useState<string | null>(reportFor?.reportId ?? null);
  const [reason, setReason] = useState<string | null>(null);
  const [description, setDescription] = useState("");
  const [actions, setActions] = useState("");
  const [role, setRole] = useState<(typeof ROLES)[number]>("оператор");
  const [duration, setDuration] = useState("");
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    if (reportFor) {
      setEqId(reportFor.equipment);
      setPinnedId(reportFor.reportId ?? null);
      setResult(null);
    }
  }, [reportFor]);

  // Отчёт дополняет выбранную в журнале запись или свежую остановку станка (идёт сейчас или закончилась до 2 ч назад).
  const draft = useMemo(() => {
    if (pinnedId) return reports.find((r) => r.id === pinnedId && r.equipment_id === eqId);
    return reports.find(
      (r) =>
        r.equipment_id === eqId &&
        r.status === "draft" &&
        r.source === "machine" &&
        (!r.ts_end || diffMin(r.ts_end, simTime) <= 120),
    );
  }, [reports, eqId, pinnedId, simTime]);
  const eq = equipment.find((e) => e.id === eqId);
  const canSend = eqId && reason && description.trim().length >= 3 && !sending;

  const submit = async () => {
    if (!eqId || !reason) return;
    setSending(true);
    try {
      await api.createReport({
        equipment_id: eqId,
        reason,
        description: description.trim(),
        actions_taken: actions.trim(),
        reporter_role: role,
        duration_min: draft ? undefined : Number(duration) || undefined,
        report_id: draft?.id,
        complete_draft: Boolean(draft),
      });
      setPinnedId(null);
      setResult({ ok: true, text: `Отчёт по «${eq?.name}» отправлен. ИИ учтёт его в анализе простоев.` });
      setReason(null);
      setDescription("");
      setActions("");
      setDuration("");
      startReport(null);
    } catch (e) {
      setResult({ ok: false, text: `Не отправлено: ${(e as Error).message}. Проверьте поля и отправьте ещё раз.` });
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="flex flex-col gap-5">
      <div>
        <div className="mb-2 font-semibold">1. Оборудование</div>
        <div className="flex flex-col gap-2">
          {AREAS.map(([areaId, areaName]) => (
            <div key={areaId} className="grid grid-cols-[130px_1fr] items-start gap-2">
              <div className="pt-2.5 text-sm text-muted">{areaName}</div>
              <div className="flex flex-wrap gap-2">
                {equipment
                  .filter((e) => e.area_id === areaId)
                  .map((e) => (
                    <button
                      key={e.id}
                      type="button"
                      onClick={() => {
                        setEqId(e.id);
                        setPinnedId(null);
                        setResult(null);
                      }}
                      className={`flex min-h-11 items-center gap-2 rounded-md border px-3 text-[15px] ${
                        e.id === eqId ? "border-ink bg-ink text-white" : "border-line bg-panel hover:bg-sunk"
                      }`}
                      aria-pressed={e.id === eqId}
                    >
                      {e.state === "down" && <span className="inline-block h-2.5 w-2.5 rounded-full bg-bad" title="Стоит сейчас" />}
                      {e.name}
                    </button>
                  ))}
              </div>
            </div>
          ))}
        </div>
        {eq && (
          <div className="mt-3 flex items-center gap-3 rounded-md bg-sunk px-3 py-2 text-sm">
            <StateChip state={eq.state} size="sm" />
            {draft ? (
              <span>
                Станок зафиксировал «{draft.machine_reason_text}» {pinnedId ? dateTime(draft.ts_start) : `в ${hhmm(draft.ts_start)}`}
                {draft.ts_end ? `, ${minutes(draft.duration_min)}` : `, идёт ${minutes(diffMin(draft.ts_start, simTime))}`}. Ваш отчёт
                дополнит эту запись.
              </span>
            ) : (
              <span className="text-muted">Незаполненной остановки нет — будет создан новый отчёт.</span>
            )}
          </div>
        )}
      </div>

      <div>
        <div className="mb-2 font-semibold">2. Причина</div>
        <div className="grid grid-cols-4 gap-2">
          {FORM_REASONS.map((code) => (
            <button
              key={code}
              type="button"
              onClick={() => setReason(code)}
              className={`min-h-12 rounded-md border px-2 text-sm leading-tight ${
                reason === code ? "border-signal bg-[#fdeedd] font-semibold" : "border-line bg-panel hover:bg-sunk"
              }`}
              aria-pressed={reason === code}
            >
              {labels[code] ?? code}
            </button>
          ))}
        </div>
      </div>

      <div>
        <label htmlFor="desc" className="mb-2 block font-semibold">
          3. Что случилось
        </label>
        <textarea
          id="desc"
          rows={3}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Например: цепь гремела с начала смены, потом оборвалась"
          className="w-full rounded-md border border-line bg-panel px-3 py-2 text-[15px]"
        />
        <AiHint eqId={eqId} description={description} actions={actions} reason={reason} onPick={setReason} />
        <input
          value={actions}
          onChange={(e) => setActions(e.target.value)}
          placeholder="Что сделали: заменили звено, натянули цепь"
          className="mt-2 w-full rounded-md border border-line bg-panel px-3 py-2 text-[15px]"
          aria-label="Что сделали"
        />
      </div>

      <div className="flex flex-wrap items-end gap-4">
        <div>
          <div className="mb-2 text-sm font-semibold">Кто заполняет</div>
          <div className="flex rounded-md border border-line bg-sunk p-0.5">
            {ROLES.map((r) => (
              <button
                key={r}
                type="button"
                onClick={() => setRole(r)}
                className={`rounded px-3 py-1.5 text-sm ${role === r ? "bg-panel font-semibold shadow-sm" : "text-muted"}`}
                aria-pressed={role === r}
              >
                {r}
              </button>
            ))}
          </div>
        </div>
        {!draft && (
          <label className="text-sm">
            <div className="mb-2 font-semibold">Длительность, мин</div>
            <input
              inputMode="numeric"
              value={duration}
              onChange={(e) => setDuration(e.target.value.replace(/\D/g, ""))}
              className="w-28 rounded-md border border-line bg-panel px-3 py-1.5"
            />
          </label>
        )}
        <button
          type="button"
          disabled={!canSend}
          onClick={submit}
          className="ml-auto min-h-12 rounded-md bg-signal px-6 text-[16px] font-semibold text-white hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {sending ? "Отправляю…" : "Отправить отчёт"}
        </button>
      </div>
      {!canSend && !sending && (
        <p className="-mt-3 text-sm text-muted">Выберите оборудование и причину и опишите, что случилось.</p>
      )}
      {result && (
        <div className={`rounded-md px-3 py-2 text-sm ${result.ok ? "bg-[#e3f4ea] text-ok" : "bg-[#fbe2df] text-bad"}`}>{result.text}</div>
      )}
    </div>
  );
}

type Filter = "all" | "draft" | "completed";

export function DowntimePage() {
  const journalSeq = useLive((s) => s.journalSeq);
  const plant = useLive((s) => s.plant);
  const startReport = useUi((s) => s.startReport);
  const [filter, setFilter] = useState<Filter>("all");
  const [area, setArea] = useState<string>("");
  const { data: reports } = usePoll(() => api.reports(area ? `&area=${area}` : ""), [journalSeq, area], 6000);
  const { data: labels } = usePoll(() => api.reasons(), [], 600000);
  const name = (id: string) => plant?.equipment.find((e) => e.id === id)?.name ?? id;
  const list = (reports ?? []).filter((r) => filter === "all" || r.status === filter);
  const drafts = (reports ?? []).filter((r) => r.status === "draft").length;

  return (
    <div className="grid min-h-0 flex-1 grid-cols-[620px_1fr] gap-4 p-4">
      <div className="scroll-thin overflow-y-auto rounded-lg bg-panel p-5">
        <Section title="Сообщить о простое" aside="для планшета у линии">
          <p className="mb-4 text-sm text-muted">
            Когда станок останавливается, система сама записывает время и оборудование. Рабочий добавляет причину и пару слов — из
            этих отчётов ИИ находит повторяющиеся проблемы.
          </p>
          <ReportForm reports={reports ?? []} labels={labels ?? {}} />
        </Section>
      </div>

      <div className="flex min-h-0 flex-col rounded-lg bg-panel p-5">
        <Section
          title="Журнал простоев"
          aside={drafts ? `не заполнено: ${drafts}` : undefined}
          className="min-h-0 flex-1"
        >
          <div className="mb-3 flex items-center gap-3">
            <div className="flex rounded-md border border-line bg-sunk p-0.5 text-sm">
              {(
                [
                  ["all", "Все"],
                  ["draft", "Не заполнены"],
                  ["completed", "Заполнены"],
                ] as [Filter, string][]
              ).map(([f, l]) => (
                <button
                  key={f}
                  type="button"
                  onClick={() => setFilter(f)}
                  className={`rounded px-3 py-1 ${filter === f ? "bg-panel font-semibold shadow-sm" : "text-muted"}`}
                  aria-pressed={filter === f}
                >
                  {l}
                </button>
              ))}
            </div>
            <select
              value={area}
              onChange={(e) => setArea(e.target.value)}
              className="rounded-md border border-line bg-panel px-2 py-1 text-sm"
              aria-label="Участок"
            >
              <option value="">Все участки</option>
              {AREAS.map(([id, n]) => (
                <option key={id} value={id}>
                  {n}
                </option>
              ))}
            </select>
          </div>
          <AnalysisStrip area={area} seq={journalSeq} />
          <div className="scroll-thin min-h-0 flex-1 overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-panel text-left text-muted">
                <tr>
                  <th className="py-2 pr-3 font-normal">Начало</th>
                  <th className="py-2 pr-3 font-normal">Оборудование</th>
                  <th className="py-2 pr-3 font-normal">Станок зафиксировал</th>
                  <th className="py-2 pr-3 font-normal">Причина от рабочего</th>
                  <th className="py-2 pr-3 font-normal">По тексту (ИИ)</th>
                  <th className="py-2 pr-3 font-normal">Описание</th>
                  <th className="py-2 text-right font-normal">Длит.</th>
                </tr>
              </thead>
              <tbody>
                {list.map((r) => (
                  <tr
                    key={r.id}
                    className="border-t border-line align-top"
                    style={r.status === "draft" ? { boxShadow: "inset 3px 0 0 var(--color-warn)" } : undefined}
                  >
                    <td className="py-2 pr-3 pl-2 whitespace-nowrap">{dateTime(r.ts_start)}</td>
                    <td className="py-2 pr-3 font-medium whitespace-nowrap">{name(r.equipment_id)}</td>
                    <td className="py-2 pr-3">{r.machine_reason_text || "—"}</td>
                    <td className="py-2 pr-3">
                      {r.status === "completed" ? (
                        (labels ?? {})[r.reason] ?? r.reason
                      ) : (
                        <button
                          type="button"
                          onClick={() => startReport(r.equipment_id, r.id)}
                          className="rounded border border-warn px-2 py-0.5 text-xs font-medium text-warn hover:bg-[#fbf1d9]"
                        >
                          Заполнить
                        </button>
                      )}
                    </td>
                    <td className="py-2 pr-3">
                      {r.ai_subtype ? (
                        <span className={r.ai_mismatch ? "font-medium text-bad" : "text-ink"} title={r.ai_mismatch ? "Причина не совпадает с текстом" : undefined}>
                          {SUBTYPE_TEXT[r.ai_subtype] ?? r.ai_subtype}
                          {r.ai_mismatch ? " ≠" : ""}
                        </span>
                      ) : (
                        <span className="text-faint">—</span>
                      )}
                    </td>
                    <td className="max-w-[380px] py-2 pr-3 text-muted">
                      {r.description}
                      {r.reporter_role && <span className="text-faint"> — {r.reporter_role}</span>}
                    </td>
                    <td className="py-2 text-right whitespace-nowrap">{r.duration_min != null ? minutes(r.duration_min) : "идёт"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      </div>
    </div>
  );
}
