// Форматы данных бэкенда — см. docs/CONTRACTS.md

export type State =
  | "running"
  | "starved"
  | "blocked"
  | "idle"
  | "down"
  | "maintenance"
  | "setup"
  | "offline";

export type Severity = "info" | "warning" | "critical";

export interface Status {
  sim_time: string;
  speed: number;
  paused: boolean;
  speeds: number[];
  seed: number;
}

export interface ShiftInfo {
  id: number;
  start: string;
  end: string;
  in_shift: boolean;
  date: string;
}

export interface Telemetry {
  ts: string;
  temperature: number;
  vibration: number;
  current: number;
  cycle_time: number;
  filter_dp: number | null;
}

export interface Maintenance {
  equipment_id: string;
  name: string;
  interval_h: number;
  hours_since: number;
  hours_left: number;
  progress: number;
  due: boolean;
  duration_min: number;
  last_done_ts: string | null;
  next_due_ts: string | null;
  window: string;
}

export interface AreaBrief {
  id: string;
  name: string;
  line_id: string | null;
  state: State;
  reason: string;
  reason_text: string;
  buffer_in?: { count: number; capacity: number | null };
  stock?: number;
}

export interface EquipmentBrief {
  id: string;
  name: string;
  area_id: string;
  type: string;
  critical: boolean;
  source: "data" | "assumption";
  state: State;
  reason: string;
  reason_text: string;
  telemetry: Telemetry | null;
  maintenance: Maintenance;
}

export interface Kpi {
  availability: number;
  performance: number;
  quality: number;
  oee: number;
  plan_units?: number;
  fact_units?: number;
  good_units?: number;
  defects?: number;
  defect_rate: number;
  run_min?: number;
  planned_min?: number;
  lost_min?: Record<string, number>;
  targets_ok: { oee: boolean; defect_rate: boolean };
  level: "ok" | "warn" | "bad";
}

export interface Targets {
  oee_min: number;
  defect_rate_max: number;
  critical_downtime_max_min_per_day: number;
  monthly_output_min: number;
  oee_red_below: number;
  critical_downtime_warn_min: number;
}

export interface KpiNow {
  sim_time: string;
  shift: ShiftInfo & { areas: Record<string, Kpi>; plant: Kpi; output: number };
  day: { areas: Record<string, Kpi>; plant: Kpi; output: number; plan: number };
  month: {
    month: string;
    output_mtd: number;
    plan_mtd: number;
    target_month: number;
    shifts_done: number;
    shifts_total: number;
  };
  targets: Targets;
}

export interface Incident {
  id: string;
  ts_start: string;
  ts_end: string | null;
  status: "open" | "closed";
  severity: Severity;
  type: string;
  area_id: string | null;
  equipment_id: string | null;
  title: string;
  details: string;
}

export interface Report {
  id: string;
  equipment_id: string;
  area_id: string;
  ts_start: string;
  ts_end: string | null;
  duration_min: number | null;
  source: string;
  status: "draft" | "completed";
  reason: string;
  description: string;
  actions_taken: string;
  reporter_role: string;
  machine_reason_text: string;
}

export interface StateEvent {
  ts: string;
  scope: "area" | "equipment";
  id: string;
  area_id: string;
  state: State;
  reason: string;
  reason_text: string;
  planned: boolean;
}

export interface UnitEvent {
  ts: string;
  unit_id: string;
  model: string;
  area_id: string;
  defect: string;
}

export interface Snapshot extends Status {
  shift: ShiftInfo;
  areas: AreaBrief[];
  equipment: EquipmentBrief[];
  kpi: KpiNow;
  incidents: Incident[];
  recent_incidents: Incident[];
  reports: Report[];
}

export interface Tick extends Status {
  areas: AreaBrief[];
  equipment: Pick<EquipmentBrief, "id" | "state" | "reason_text" | "telemetry">[];
  events: StateEvent[];
  units: UnitEvent[];
  reports: Report[];
  incidents: Incident[];
}

export interface ParetoReason {
  reason_text: string;
  minutes: number;
  count: number;
  planned: boolean;
  kind: "equipment" | "planned" | "micro" | "setup" | "flow";
  share: number;
  cumulative: number;
}

export interface ShiftKpi {
  date: string;
  shift: number;
  oee: number;
  availability: number;
  performance: number;
  quality: number;
  defect_rate: number;
  fact_units: number;
  run_min: number;
}

export interface AreaView {
  area: AreaBrief & { source: string };
  equipment: EquipmentBrief[];
  kpi: { shift: Kpi | null; day: Kpi | null; history: ShiftKpi[] };
  pareto: {
    days: number;
    reasons: ParetoReason[];
    equipment: { equipment_id: string; name: string; minutes: number; count: number }[];
  };
  reports: Report[];
  incidents: Incident[];
  targets: Targets;
  shift: ShiftInfo;
}

export interface EquipmentView extends EquipmentBrief {
  telemetry_series: {
    ts: string[];
    temperature: number[];
    vibration: number[];
    current: number[];
    filter_dp: number[] | null;
  };
  telemetry_norm: Record<string, { mean: number; std: number }>;
  filter: { dp_limit_pa: number; dp_defect_from_pa: number } | null;
  stops: { start: string; end: string; minutes: number; reason_text: string; planned: boolean }[];
  reports: Report[];
}

export interface PlantArea {
  id: string;
  name: string;
  line_id: string | null;
  source: string;
}

export interface PlantEquipment {
  id: string;
  name: string;
  area: string;
  type: string;
  critical: boolean;
  source: string;
}

export interface Plant {
  areas: PlantArea[];
  equipment: PlantEquipment[];
  models: { id: string; name: string; plan_month_units: number }[];
  rates: { plan_units_per_shift: number; takt_min: number; ideal_cycle_min: number };
  process: Record<string, { cycle_min: number }>;
  defect_names: Record<string, string>;
}

export interface EventsWindow {
  from: string;
  to: string;
  initial: StateEvent[];
  events: StateEvent[];
}

export interface Finding {
  severity: Severity;
  kind: string;
  title: string;
  details: string;
}

export interface ImportResult {
  id: number;
  imported_at: string;
  files: string[];
  is_default?: boolean;
  rows: Record<string, number>;
  tables: Record<string, Record<string, string | number>[]>;
  kpi_rows: (Record<string, string | number> & {
    date: string;
    line_id: string;
    area: string;
    oee: number;
    availability: number;
    performance: number;
    quality: number;
    defect_rate: number;
  })[];
  reconciliation: { date: string; line_id: string; area: string; lost_min: number; registered_min: number; gap_min: number }[];
  findings: Finding[];
  warnings: string[];
  targets: Targets;
  scheme: string[];
}
