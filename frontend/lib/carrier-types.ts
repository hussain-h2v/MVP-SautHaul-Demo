// Hand-written contract types for the carrier portal and notifications (until the OpenAPI client is generated).
import type { DriverRow, Shipment } from "./admin-types";

export interface Problem {
  code: string;
  message: string;
}

export interface AssignmentCheck {
  problems: Problem[];
  warnings: Problem[];
  driver_language: string | null;
  driver_verified: boolean | null;
}

export interface AssignResult {
  shipment: Shipment;
  warnings: Problem[];
  driver_language: string | null;
}

export interface DriverHistoryRow {
  code: string;
  current_status: string;
  facility_code: string | null;
  original_eta_ts: string | null;
}

export interface DriverDetail extends DriverRow {
  home_base_city: string | null;
  history: DriverHistoryRow[];
}

export interface VerificationSent {
  sent: boolean;
  expires_at: string;
  dev_code?: string;
}

export interface VehicleRow {
  id: string;
  code: string;
  carrier_id: string;
  carrier_name: string;
  vehicle_type_code: string;
  vehicle_type_description: string;
  registration_number: string;
  capacity_kg: number;
  refrigeration_capable: boolean;
  heavy_capable: boolean;
  active_flag: boolean;
  assigned_shipments: number;
}

export type HoldState = "none" | "held" | "pending_confirmation" | "request_waiting" | "request_suggested";

export interface TrackerRow {
  shipment_id: string;
  code: string;
  order_reference: string;
  current_status: string;
  load: { required_dock_type: string; temperature_control_required: boolean; weight_kg: number };
  vehicle: { id: string; registration_number: string } | null;
  driver: { id: string; name: string; language: string | null } | null;
  facility: { id: string; code: string; name: string };
  appointment: {
    id: string;
    status: string;
    slot_code: string | null;
    dock_code: string | null;
    start: string | null;
    end: string | null;
  } | null;
  eta: { ts: string | null; source: string | null; confidence: string | null; declared_by: string | null };
  checkin: { arrival_state: string | null; gate_in_ts: string | null; queue_state: string | null } | null;
  hold_state: HoldState;
  escalation: { status: string; reason_code: string } | null;
}

export type SlotChangeKind =
  | "confirmed"
  | "pending_confirmation"
  | "held"
  | "suggested"
  | "rejected"
  | "cancelled"
  | "replaced"
  | "no_show"
  | "escalated";

export interface SlotChange {
  ts: string;
  shipment_id: string;
  shipment_code: string;
  kind: SlotChangeKind;
  reason: string | null;
  slot_code: string | null;
  start: string | null;
}

export interface CarrierDashboard {
  drivers_available: number;
  trucks_on_road: number;
  late_trucks: number;
  awaiting_assignment: number;
  upcoming_appointments_today: number;
  detention_hours: number;
  unverified_drivers: number;
  shipments_total: number;
}

export interface NotificationItem {
  id: string;
  type: string;
  title: string;
  body: string | null;
  payload: Record<string, unknown> | null;
  created_at: string;
  read: boolean;
}

export interface NotificationPage {
  total: number;
  unread: number;
  items: NotificationItem[];
}
