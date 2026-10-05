import type {
  AreaView,
  EquipmentView,
  EventsWindow,
  ImportResult,
  Incident,
  KpiNow,
  Maintenance,
  Plant,
  Report,
  ShiftKpi,
  Snapshot,
  Status,
} from "../types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { headers: { Accept: "application/json", ...(init?.headers ?? {}) }, ...init });
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* тело без JSON */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  body: JSON.stringify(body),
  headers: { "Content-Type": "application/json" },
});

export interface ReconRow {
  date: string;
  shift: number;
  area_id: string;
  lost_min: number;
  registered_min: number;
  unregistered_min: number;
  breakdown: Record<string, number>;
}

export interface NewReport {
  equipment_id: string;
  reason: string;
  description: string;
  actions_taken: string;
  reporter_role: string;
  duration_min?: number;
  report_id?: string;
  complete_draft?: boolean;
}

export const api = {
  plant: () => request<Plant>("/api/plant"),
  state: () => request<Snapshot>("/api/state"),
  kpi: () => request<KpiNow>("/api/kpi"),
  kpiHistory: (area: string, shifts = 12) => request<ShiftKpi[]>(`/api/kpi/history?area=${area}&shifts=${shifts}`),
  area: (id: string) => request<AreaView>(`/api/areas/${id}`),
  equipment: (id: string, hoursBack = 8) => request<EquipmentView>(`/api/equipment/${id}?hours=${hoursBack}`),
  events: (hoursBack = 8) => request<EventsWindow>(`/api/events?hours=${hoursBack}`),
  maintenance: () => request<Maintenance[]>("/api/maintenance"),
  reconciliation: (days = 7) => request<ReconRow[]>(`/api/reconciliation?days=${days}`),
  incidents: (limit = 100) => request<Incident[]>(`/api/incidents?limit=${limit}`),
  reasons: () => request<Record<string, string>>("/api/reasons"),
  reports: (q = "") => request<Report[]>(`/api/reports?limit=200${q}`),
  createReport: (r: NewReport) => request<Report>("/api/reports", json(r)),
  control: (body: { speed?: number; paused?: boolean; reset?: boolean }) =>
    request<Status>("/api/sim/control", json(body)),
  scenarios: () => request<Record<string, { title: string; details: string }>>("/api/scenarios"),
  trigger: (name: string) => request<{ title: string }>(`/api/scenarios/${name}/trigger`, { method: "POST" }),
  latestImport: () => request<ImportResult>("/api/ingest/latest"),
  upload: (files: FileList) => {
    const fd = new FormData();
    Array.from(files).forEach((f) => fd.append("files", f));
    return request<ImportResult>("/api/ingest", { method: "POST", body: fd });
  },
};
