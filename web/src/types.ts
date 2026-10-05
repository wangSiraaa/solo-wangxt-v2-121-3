export interface CurvePoint {
  temp_c: number;
  recovered_pct: number;
}

export interface DensityRow {
  temp_c: number;
  density_g_cm3: number;
}

export interface Experiment {
  id: number;
  name: string;
  sample_id?: string | null;
  feed_density_g_cm3: number;
  residue_density_g_cm3?: number | null;
  conditions: Record<string, unknown>;
  points: CurvePoint[];
  density_rows: DensityRow[];
  notes?: string | null;
  plans?: SavedPlanSummary[];
}

export interface SavedPlanSummary {
  id: number;
  name: string;
  basis: "volume" | "mass";
  loss_pct: number;
  cuts: CutInput[];
}

export interface CutInput {
  name: string;
  start_temp_c: number;
  end_temp_c: number;
}

export interface PlanInput {
  name: string;
  basis: "volume" | "mass";
  loss_pct: number;
  cuts: CutInput[];
}

export interface Issue {
  code: string;
  severity: "error" | "warning" | "info";
  message: string;
}

export interface CutResult extends CutInput {
  index: number;
  flags: string[];
  start_recovery_pct: number | null;
  end_recovery_pct: number | null;
  clipped_range_c: [number, number] | null;
  volume_yield_pct: number | null;
  mass_yield_pct: number | null;
}

export interface Overlap {
  cut_a: number;
  cut_b: number;
  cut_a_name: string;
  cut_b_name: string;
  from_temp_c: number;
  to_temp_c: number;
  width_c: number;
  volume_pct: number | null;
  mass_pct?: number | null;
  partial_outside_range: boolean;
  fully_outside_range: boolean;
}

export interface Gap {
  kind: "front" | "inter" | "tail";
  from_temp_c: number;
  to_temp_c: number;
  width_c: number;
  after_cut: string | null;
  before_cut: string | null;
  volume_pct: number | null;
  mass_pct?: number | null;
  partial_outside_range: boolean;
  fully_outside_range: boolean;
}

export interface MassTotals {
  nominal_yield_pct: number;
  union_yield_pct: number;
  overlap_pct: number;
  front_gap_pct: number;
  inter_gap_pct: number;
  tail_gap_pct: number;
  uncut_distillate_pct: number | null;
  light_unassigned_pct: number | null;
  residue_bottoms_pct: number | null;
  residue_bottoms_gross_pct: number | null;
  residual_total_pct: number | null;
  loss_pct: number;
  identity_sum_pct: number | null;
  identity_ok: boolean;
  identity_note: string;
  residue_density_g_cm3: number | null;
}

export interface Totals {
  nominal_yield_pct: number;
  union_yield_pct: number;
  overlap_pct: number;
  front_gap_pct: number;
  inter_gap_pct: number;
  tail_gap_pct: number;
  uncut_distillate_pct: number;
  light_unassigned_pct: number;
  residue_bottoms_pct: number;
  residue_bottoms_gross_pct: number;
  residual_total_pct: number;
  loss_pct: number;
  identity_sum_pct: number;
  identity_residual_pct: number;
  identity_ok: boolean;
  mass: MassTotals | null;
}

export interface EvalResult {
  basis: string;
  applicable_range: {
    temp_c: [number, number];
    recovered_pct: [number, number];
    extrapolation: string;
  };
  cuts: CutResult[];
  overlaps: Overlap[];
  gaps: Gap[];
  totals: Totals;
  issues: Issue[];
  has_blocking_errors: boolean;
  method: Record<string, string>;
}

export interface CurveSample {
  temps_c: number[];
  recovered_pct: number[];
  raw_points: CurvePoint[];
  range: { temp_c: [number, number]; recovered_pct: [number, number] };
  issues: Issue[];
  has_blocking_errors: boolean;
}

// ---- 切点敏感性预览 ----
export type ScenarioKey = "down" | "base" | "up";

export interface SensitivityRequest {
  plan: PlanInput;
  cut_index: number;
  endpoint: "start" | "end";
  step_c: number;
}

export interface SensitivityMember {
  cut_index: number;
  endpoint: "start" | "end";
  cut_name: string;
}

export interface SensitivityCutBrief {
  start_temp_c: number;
  end_temp_c: number;
  flags: string[];
  volume_yield_pct: number | null;
  mass_yield_pct: number | null;
  start_recovery_pct: number | null;
  end_recovery_pct: number | null;
}

export interface SensitivityCutCompare {
  index: number;
  name: string;
  is_perturbed: boolean;
  shares_endpoint: boolean;
  yield_changed: boolean;
  max_abs_volume_delta: number;
  max_abs_mass_delta: number;
  scenarios: Record<ScenarioKey, SensitivityCutBrief>;
  delta_down_volume_pct: number | null;
  delta_up_volume_pct: number | null;
  delta_down_mass_pct: number | null;
  delta_up_mass_pct: number | null;
}

export interface SensitivityItemBrief {
  from_temp_c: number;
  to_temp_c: number;
  width_c: number;
  volume_pct: number | null;
  mass_pct: number | null;
  partial_outside_range: boolean;
  fully_outside_range: boolean;
}

export interface SensitivityOverlapCompare {
  cut_a: number;
  cut_b: number;
  cut_a_name: string;
  cut_b_name: string;
  appears_or_disappears: boolean;
  scenarios: Record<ScenarioKey, SensitivityItemBrief | null>;
}

export interface SensitivityGapCompare {
  kind: "front" | "inter" | "tail";
  after_cut: string | null;
  before_cut: string | null;
  appears_or_disappears: boolean;
  scenarios: Record<ScenarioKey, SensitivityItemBrief | null>;
}

export interface SensitivityBoundaryScenario {
  temp_c: number;
  in_range: boolean;
  exceeds: "below" | "above" | null;
  out_of_range_width_c: number;
  cut_flags: string[];
  member_cut_flags: Record<string, string[]>;
  any_member_out_of_range: boolean;
  clipped_range_c: [number, number] | null;
  has_blocking_errors: boolean;
}

export interface SensitivityTotals {
  [k: string]: unknown;
  nominal_yield_pct: number;
  union_yield_pct: number;
  overlap_pct: number;
  front_gap_pct: number;
  inter_gap_pct: number;
  tail_gap_pct: number;
  uncut_distillate_pct: number;
  light_unassigned_pct: number;
  residue_bottoms_pct: number;
  residue_bottoms_gross_pct: number;
  residual_total_pct: number;
  identity_sum_pct: number | null;
  identity_residual_pct?: number;
  identity_ok: boolean;
  mass: Record<string, unknown> | null;
}

export interface SensitivityPreview {
  selection: {
    cut_index: number;
    cut_name: string;
    endpoint: "start" | "end";
    original_temp_c: number;
    endpoint_other_temp_c: number;
    step_c: number;
    member_endpoints: SensitivityMember[];
  };
  applicable_range: { temp_c: [number, number]; extrapolation: string };
  scenario_temps_c: Record<ScenarioKey, number>;
  boundary: {
    original_temp_c: number;
    temp_range_c: [number, number];
    scenarios: Record<ScenarioKey, SensitivityBoundaryScenario>;
  };
  cuts: SensitivityCutCompare[];
  overlaps: SensitivityOverlapCompare[];
  gaps: SensitivityGapCompare[];
  totals: Record<ScenarioKey, SensitivityTotals>;
  issues: Record<ScenarioKey, Issue[]>;
  apply: {
    member_endpoints: SensitivityMember[];
    candidate_temps_c: Record<ScenarioKey, number>;
  };
  note: string;
}
