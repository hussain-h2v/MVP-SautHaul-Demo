// Hand-written contract types for the facility portal (until the OpenAPI client is generated).
export type DockType = "STANDARD" | "REEFER" | "HEAVY";
export type DockStatus = "ACTIVE" | "MAINTENANCE" | "OUT_OF_SERVICE" | "INACTIVE";

export interface Dock {
  id: string;
  code: string;
  facility_id: string;
  dock_code: string;
  dock_type: DockType;
  supports_refrigerated: boolean;
  max_vehicle_weight_kg: number;
  dock_status: DockStatus;
  compatible_vehicle_type_codes: string[];
  notes: string | null;
}

export interface VehicleType {
  code: string;
  description: string;
}

export type SlotStatus = "OPEN" | "BLOCKED" | "CLOSED";

export interface SlotRow {
  id: string;
  code: string;
  dock_id: string;
  dock_code: string;
  start: string;
  end: string;
  slot_status: SlotStatus;
  block_reason: string | null;
  booked: boolean;
}

export interface SlotTemplate {
  dock_type: DockType;
  start: string;
  end: string;
  length_min: number;
}

export interface GenerateResult {
  dry_run: boolean;
  to_create: number;
  skipped_overlap: number;
  per_dock: { dock_code: string; count: number }[];
}

export interface AffectedAppointment {
  appointment_id: string;
  shipment_code: string;
  slot_code: string;
  slot_start_ts: string;
  appointment_status: string;
}

export interface BulkStatusResult {
  applied: boolean;
  updated: number;
  affected_appointments: AffectedAppointment[];
}

export interface CopyDayResult {
  dry_run: boolean;
  to_create: number;
  skipped_overlap: number;
}

export type DockEventType = "MAINTENANCE" | "BREAKDOWN" | "CAPACITY_REDUCTION" | "REOPENED" | "MANUAL_BLOCK";

export interface DockEvent {
  id: string;
  dock_id: string;
  dock_code: string;
  event_type: DockEventType;
  event_start_ts: string;
  event_end_ts: string | null;
  reason: string;
  resolved: boolean;
  affected_count: number;
}

export interface DockEventResult extends DockEvent {
  affected_appointments: AffectedAppointment[];
}

export interface RuleType {
  type: string;
  description: string;
  value_hint: string;
}

export interface FacilityRule {
  id: string;
  rule_type: string;
  rule_value: string;
  description: string;
  effective_from: string | null;
  effective_to: string | null;
  active_flag: boolean;
}

export interface AuditRow {
  actor_type: string;
  actor_id: string | null;
  action: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  created_at: string;
}

export type SlotState =
  | "completed"
  | "in_progress"
  | "confirmed"
  | "pending_confirmation"
  | "held"
  | "cancelled"
  | "no_show"
  | "open"
  | "blocked"
  | "breakdown"
  | "maintenance"
  | "reduced_capacity";

export interface ScheduleAppointment {
  id: string;
  code: string;
  status: string;
  shipment_code: string;
  carrier_name: string | null;
  driver_name: string | null;
  priority_code: string;
}

export interface ScheduleSlot {
  slot_id: string;
  code: string;
  start: string;
  end: string;
  state: SlotState;
  block_reason: string | null;
  history_state: string | null;
  event: { event_type: string; reason: string } | null;
  appointment: ScheduleAppointment | null;
}

export interface ScheduleDock {
  id: string;
  code: string;
  dock_code: string;
  dock_type: DockType;
  dock_status: DockStatus;
  slots: ScheduleSlot[];
}

export interface Schedule {
  facility: { id: string; code: string; facility_name: string; timezone: string; open_time: string; close_time: string };
  date: string;
  docks: ScheduleDock[];
}

export interface SlotDetail {
  slot: { id: string; code: string; dock_code?: string; start: string; end: string; slot_status: string; block_reason: string | null };
  appointment: Record<string, unknown> | null;
  shipment: Record<string, unknown> | null;
  driver: Record<string, unknown> | null;
  vehicle: Record<string, unknown> | null;
  eta: { ts: string | null; source: string | null; confidence: string | null } | null;
  history: Record<string, unknown>[];
}

export interface PendingAppointment {
  appointment_id: string;
  shipment_id: string;
  code: string;
  shipment_code: string;
  carrier_name: string | null;
  driver_name: string | null;
  priority_code: string;
  slot_code: string;
  dock_code: string;
  slot_start_ts: string;
  slot_end_ts: string;
  booked_at: string;
  expires_at: string;
  reason: "STARTS_AFTER_LAST_START" | "NEEDS_CONFIRMATION";
}

export interface InboundRow {
  shipment_id: string;
  shipment_code: string;
  carrier_name: string | null;
  driver_name: string | null;
  priority_code: string;
  required_dock_type: string;
  current_status: string;
  eta_ts: string | null;
  eta_source: string | null;
  eta_confidence: string | null;
  appointment_id: string | null;
  appointment_status: string | null;
  slot_code: string | null;
  dock_code: string | null;
  slot_start_ts: string | null;
  late: boolean;
  at_risk: boolean;
}

export interface YardRow {
  shipment_id: string;
  shipment_code: string;
  carrier_name: string | null;
  driver_name: string | null;
  priority_code: string;
  load: string;
  appointment_id: string | null;
  appointment_status: string | null;
  slot_code: string | null;
  planned_dock_code: string | null;
  actual_dock_code: string | null;
  slot_start_ts: string | null;
  slot_end_ts: string | null;
  eta_ts: string | null;
  gate_in_ts: string | null;
  queue_state: string | null;
  queue_position: number | null;
  waiting_min: number | null;
  arrival_state: string | null;
  unload_start_ts: string | null;
  unload_end_ts: string | null;
  overrun_min: number | null;
  dock_mismatch: boolean;
  checkin_id: string | null;
}

export interface Yard {
  queue: YardRow[];
  in_dock: YardRow[];
  expected: YardRow[];
  done: YardRow[];
}

export interface FacilityHome {
  date: string;
  utilisation_pct: number;
  inbound_count: number;
  in_yard_count: number;
  active_holds: number;
  open_exceptions: number;
  dock_status: { active: number; maintenance: number; out_of_service: number; inactive: number; events_open: number };
  pending_confirmations: number;
}

export interface ReportResult {
  kind: string;
  columns: string[];
  rows: Record<string, unknown>[];
}

export interface FacilitySummary {
  id: string;
  code: string;
  facility_name: string;
  open_time: string;
  close_time: string;
  timezone: string;
  active_flag: boolean;
}

export interface SchedulingOption {
  rank: number;
  slot_ids: string[];
  slot_codes: string[];
  dock_code: string;
  dock_type: DockType;
  start: string;
  end: string;
  needs_planner_approval: boolean;
  reasons: string[];
  explanation: string;
}

export interface SchedulingOptions {
  shipment_id: string;
  eta: { ts: string; source: string; confidence: string; upper_ts: string | null; requires_human_review: boolean } | null;
  total_feasible: number;
  options: SchedulingOption[];
  rejections: Record<string, number>;
}

export interface MoveResult {
  appointment_id: string;
  code: string;
  appointment_status: "CONFIRMED" | "PENDING_CONFIRMATION";
  is_current: boolean;
  slot_id: string;
  replaced_appointment_id: string | null;
  needs_planner_approval: boolean;
}

export interface HoldRow {
  id: string;
  shipment_id: string;
  shipment_code: string | null;
  slot_ids: string[];
  status: string;
  expires_at: string;
  seconds_left: number;
}
