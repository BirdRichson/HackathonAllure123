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
  // Разметка ИИ: что случилось по тексту и совпадает ли с выбранной причиной
  ai_subtype?: string | null;
  ai_reason?: string | null;
  ai_confidence?: number | null;
  ai_source?: "ml" | "llm" | "rules" | null;
  ai_component?: string | null;
  ai_mismatch?: boolean | null;
  ai_note?: string | null;
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
  predictions: Predictions;
  ai: AiBrief;
}

// ─────────────────────────────── ИИ ───────────────────────────────

export interface AiBrief {
  llm_online: boolean;
  llm_label: string | null;
  failure_model: boolean;
}

export interface InsightEffect {
  cars_month?: number;
  defects_month?: number;
  minutes_month?: number;
  text: string;
}

export interface Insight {
  id: string;
  kind: string;
  severity: Severity;
  area_id: string | null;
  equipment_ids: string[];
  title: string;
  summary: string;
  evidence: string[];
  recommendation: string;
  effect: InsightEffect;
  cost?: string;
  assumptions?: string[];
  confidence: string;
  source: "llm" | "rules";
  rank: number;
}

export interface Recurring {
  equipment_id: string;
  name: string;
  subtype: string;
  subtype_label: string;
  count: number;
  minutes: number;
  components: { name: string; count: number }[];
}

export interface ReportsAnalysis {
  total: number;
  completed: number;
  drafts: number;
  draft_share: number;
  mismatches: number;
  mismatch_share: number;
  mismatch_chosen: { reason: string; count: number }[];
  mismatch_examples: {
    id: string;
    equipment_id: string;
    name: string;
    ts_start: string;
    description: string;
    chosen: string;
    ai: string;
    ai_subtype: string;
    confidence: number;
  }[];
  by_subtype: { subtype: string; label: string; count: number; minutes: number }[];
  recurring: Recurring[];
}

export interface InsightsState {
  generated_at: string;
  period: { from: string; to: string; workdays: number };
  summary: string;
  summary_source: "llm" | "rules";
  items: Insight[];
  llm: { provider: string; model: string; label: string; cached: boolean; latency_ms: number; rejected_by_guard: number } | null;
  llm_status: "ok" | "pending" | "offline" | "error";
  llm_error: string | null;
  reports: ReportsAnalysis;
  loss_by_area: Record<string, number>;
}

export interface RiskFactor {
  feature: string;
  label: string;
  value: string;
  weight: number;
}

export interface PredictionItem {
  equipment_id: string;
  name: string;
  area_id: string;
  type: string;
  status: string;
  kind: "ml" | "rule" | "filter" | "base_rate";
  level: "low" | "medium" | "high";
  failure: string;
  note: string;
  risk?: number | null;
  alert?: boolean;
  threshold?: number;
  factors?: RiskFactor[];
  indicator?: number | null;
  per_month?: number;
  dp?: number | null;
  swap_pa?: number;
  limit_pa?: number;
  rate_pa_h?: number | null;
  hours_to_swap?: number | null;
  hours_to_limit?: number | null;
  limit_ts?: string | null;
}

export interface Predictions {
  horizon_min: number;
  updated: string;
  model_loaded: boolean;
  items: PredictionItem[];
  stats_30d: { failures: number; predicted: number; mean_lead_min: number | null };
}

export interface PlanForecast {
  as_of: string;
  month: string;
  target: number;
  plan_models: number;
  output_mtd: number;
  p10: number;
  p50: number;
  p90: number;
  prob_target: number;
  shift_mean: number;
  shift_std: number;
  shifts_left: number;
  shifts_total: number;
  required_per_shift: number | null;
  max_theoretical: number;
  band: { date: string; p10: number; p50: number; p90: number }[];
  actual: { date: string; cum: number }[];
  by_model: { model: string; plan: number; mtd: number; forecast: number; share: number }[];
}

export interface Suggestion {
  prediction: {
    subtype: string;
    subtype_label: string;
    reason: string;
    reason_label: string;
    confidence: number;
    source: "ml" | "llm" | "rules";
    component: string;
    note: string;
  } | null;
  mismatch: boolean;
  llm_error?: string;
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
