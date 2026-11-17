// Types for the coordinator desk API (/coordinator/*, /booking/*). Hand-written until the OpenAPI client is generated.

export type Priority = "CRITICAL" | "HIGH" | "NORMAL" | "LOW";
export type InboxKind = "request" | "exception" | "hold" | "escalation" | "failed_message" | "eta_change";

export interface PersonRef {
  id: string;
  name: string;
}

export interface InboxItem {
  key: string;
  kind: InboxKind;
  id: string;
  shipment_id: string | null;
  shipment_code: string | null;
  carrier_name: string | null;
  facility_code: string | null;
  priority_code: Priority | string | null;
  status: string;
  title: string;
  summary: string;
  created_at: string;
  expires_at: string | null;
  claimed_by: PersonRef | null;
}

export interface InboxCounters {
  requests: number;
  exceptions: number;
  holds_expiring: number;
  escalations: number;
  failed_messages: number;
  eta_changes: number;
  total: number;
}

export interface Inbox {
  counters: InboxCounters;
  items: InboxItem[];
}

export interface ClaimResult {
  claimed_by: PersonRef;
  expires_at: string;
}

export interface CoordOption {
  rank: number;
  slot_ids: string[];
  slot_codes: string[];
  dock_code: string;
  dock_type: string;
  start: string;
  end: string;
  needs_planner_approval: boolean;
  reasons: string[];
  explanation: string;
}

export type RecommendedAction = "approve" | "suggest" | "hold" | "escalate" | "reject";

export interface RequestDetail {
  request: {
    id: string;
    status: string;
    reason_code: string | null;
    created_at: string;
    decision_deadline: string | null;
    reason: string | null;
    hold_id: string | null;
  };
  shipment: {
    id: string;
    code: string;
    priority_code: Priority | string;
    required_dock_type: string;
    load_weight_kg: number;
    expected_unload_min: number;
    temperature_control_required: boolean;
    carrier_name: string | null;
    driver_name: string | null;
    driver_language: string | null;
    driver_phone: string | null;
  };
  facility: { id: string; code: string; name: string };
  current_appointment: {
    id: string;
    status: string;
    slot_code: string;
    dock_code: string;
    start: string;
    end: string;
  } | null;
  eta: { ts: string; source: string; confidence: string; upper_ts: string | null; requires_human_review: boolean } | null;
  eta_history: {
    created_at: string;
    declared_eta_ts: string;
    source: string;
    confidence: string;
    reason: string | null;
    note: string | null;
  }[];
  facts: {
    exception_id: string | null;
    reason: string | null;
    reported_delay_min: number | null;
    declared_eta_ts: string | null;
    earliest_acceptable_ts: string | null;
    latest_acceptable_ts: string | null;
    description: string | null;
    original_message: string | null;
    translation: string | null;
    confidence: string | null;
    requires_human_review: boolean;
  } | null;
  held_option: {
    hold_id: string;
    slot_ids: string[];
    slot_codes: string[];
    dock_code: string;
    start: string;
    end: string;
    expires_at: string;
    seconds_left: number;
    feasible: boolean;
    problems: string[];
  } | null;
  options: CoordOption[];
  recommendation: {
    action: RecommendedAction;
    slot_ids: string[];
    reasons: string[];
    impact: string[];
    risk_flags: string[];
    source: string;
  };
  claimed_by: PersonRef | null;
}

export interface Booked {
  appointment_id: string;
  code: string;
  appointment_status: "CONFIRMED" | "PENDING_CONFIRMATION" | string;
  is_current: boolean;
  slot_id: string;
  replaced_appointment_id: string | null;
  needs_planner_approval: boolean;
}

export interface CompetingRequest {
  request_id: string;
  shipment_code: string;
  priority_code: Priority | string;
  rank: number;
  score: number;
  fixed: boolean;
  tie_with_next: boolean;
  reasons: string[];
  hold_id: string | null;
  waiting_min: number;
}

export interface CompetingGroup {
  key: string;
  slot_id: string;
  slot_code: string;
  dock_code: string;
  start: string;
  facility_code: string;
  requests: CompetingRequest[];
}

export interface CompetingResult {
  groups: CompetingGroup[];
}

export interface DecideResult {
  approved_appointment_id: string;
  overrode_policy: boolean;
  policy_winner_request_id: string;
}

export interface Escalation {
  id: string;
  shipment_id: string | null;
  shipment_code: string | null;
  carrier_name: string | null;
  driver_name: string | null;
  driver_phone: string | null;
  reason_code: string;
  status: "open" | "in_progress" | "resolved";
  handoff_record: Record<string, unknown>;
  assigned_to: PersonRef | null;
  resolution: string | null;
  created_at: string;
  closed_at: string | null;
}

export type SenderType = "DRIVER" | "AGENT" | "OPERATIONS" | "WAREHOUSE" | "SYSTEM";

export interface ThreadSummary {
  id: string;
  code: string;
  driver_name: string;
  driver_language: string | null;
  driver_phone: string | null;
  shipment_code: string | null;
  thread_status: string;
  thread_intent: string;
  last_message_text: string | null;
  last_message_ts: string | null;
  requires_review: boolean;
  taken_over_by: PersonRef | null;
  bot_paused: boolean;
}

export interface ThreadPage {
  total: number;
  items: ThreadSummary[];
}

export interface ChatMsg {
  id: string;
  sender_type: SenderType;
  text: string;
  translation: string | null;
  ts: string;
  is_duplicate: boolean;
  parsed_intent: string | null;
  extracted_eta_ts: string | null;
  requires_human_review: boolean;
}

export interface ThreadMessages {
  thread: ThreadSummary;
  messages: ChatMsg[];
}

export interface Draft {
  text: string;
  language: string | null;
  source: string;
}

export interface BoardRow {
  shipment_id: string;
  code: string;
  carrier_name: string | null;
  driver_name: string | null;
  facility_code: string;
  priority_code: Priority | string;
  current_status: string;
  eta_ts: string | null;
  eta_confidence: string | null;
  slot_code: string | null;
  dock_code: string | null;
  slot_start_ts: string | null;
  late_min: number | null;
}

export const BOARD_STAGES = ["travelling", "late", "in_yard", "unloading", "done"] as const;
export type BoardStage = (typeof BOARD_STAGES)[number];

export interface Board {
  date: string;
  stages: Record<BoardStage, BoardRow[]>;
  counts: Record<string, number>;
}

export interface HandoverDraft {
  shift_started_at: string;
  summary: string;
  snapshot: Record<string, unknown>;
}

export interface HandoverRecord {
  id: string;
  author_name: string;
  shift_started_at: string;
  summary: string;
  notes: string | null;
  created_at: string;
}

export interface ActivityRow {
  ts: string;
  entity: string;
  entity_id: string | null;
  action: string;
  summary: string;
  outcome: string | null;
}
