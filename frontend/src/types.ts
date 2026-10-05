export interface Health {
  status: string;
  version: string;
  data_mode: "demo" | "plant";
  time: string;
}

export interface Targets {
  oee_min: number;
  defect_rate_max: number;
  critical_downtime_max_min_per_day: number;
  monthly_output_min: number;
  oee_red_below: number;
  critical_downtime_warn_min: number;
}

export type Source = "data" | "assumption";

export interface Area {
  id: string;
  name: string;
  line_id: string | null;
  source: Source;
}

export interface Equipment {
  id: string;
  name: string;
  area: string;
  type: string;
  critical: boolean;
  source: Source;
}

export interface PlantModel {
  id: string;
  name: string;
  plan_month_units: number;
}

export interface Shift {
  id: number;
  start: string;
  end: string;
}

export interface Plant {
  meta: { name: string; timezone: string };
  schedule: { shifts_per_day: number; shift_hours: number; shifts: Shift[] };
  rates: { plan_units_per_shift: number; takt_min: number; ideal_cycle_min: number };
  models: PlantModel[];
  flow: string[];
  areas: Area[];
  equipment: Equipment[];
}
