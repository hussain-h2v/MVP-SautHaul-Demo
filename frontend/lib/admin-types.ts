// Hand-written contract types for the admin portal (until the OpenAPI client is generated).
export interface Page<T> {
  total: number;
  items: T[];
}

export interface Facility {
  id: string;
  code: string;
  facility_name: string;
  address: string | null;
  city: string;
  state: string;
  timezone: string;
  open_time: string;
  close_time: string;
  checkin_grace_min: number;
  default_unload_min: number;
  active_flag: boolean;
  notes: string | null;
}

export interface FacilityContact {
  id: string;
  contact_role: string;
  contact_name: string;
  email: string | null;
  phone: string | null;
  active_flag: boolean;
  missing_email: boolean;
}

export interface FacilityDetail extends Facility {
  contacts: FacilityContact[];
  dock_count: number;
}

export interface Carrier {
  id: string;
  code: string;
  carrier_name: string;
  contact_email: string | null;
  contact_phone: string | null;
  active_flag: boolean;
  allowed_vehicle_type_codes: string[];
  driver_count: number;
  vehicle_count: number;
}

export interface CarrierDetail extends Carrier {
  shipments_total: number;
  shipments_active: number;
  shipments_completed: number;
  shipments_cancelled: number;
}

export interface VehicleType {
  code: string;
  description: string;
}

export type UserRole = "admin" | "facility_planner" | "coordinator" | "carrier_user";
export type UserStatus = "active" | "disabled" | "invited";

export interface AdminUser {
  id: string;
  email: string;
  full_name: string;
  role: UserRole;
  status: UserStatus;
  locale: string;
  facility_ids: string[];
  carrier_id: string | null;
}

export interface InvitedUser extends AdminUser {
  invite_token: string;
}

export interface DriverRow {
  id: string;
  code: string;
  carrier_id: string;
  carrier_name: string;
  driver_name: string;
  phone: string;
  whatsapp_number: string | null;
  preferred_language: string;
  whatsapp_opt_in: boolean;
  verified: boolean;
  driver_status: string;
  licence_number: string;
  active_shipments: number;
  last_activity: string | null;
}

export type DockType = "ANY" | "STANDARD" | "REEFER" | "HEAVY";
export type Priority = "LOW" | "NORMAL" | "HIGH" | "CRITICAL";
export type ShipmentStatus =
  | "PLANNED"
  | "ASSIGNED"
  | "IN_TRANSIT"
  | "AT_GATE"
  | "WAITING"
  | "IN_DOCK"
  | "COMPLETED"
  | "CANCELLED";
export type OfferStatus = "draft" | "offered" | "accepted" | "declined";

export interface Shipment {
  id: string;
  code: string;
  order_reference: string;
  carrier_id: string | null;
  carrier_name: string | null;
  driver_id: string | null;
  driver_name: string | null;
  vehicle_id: string | null;
  destination_facility_id: string;
  facility_code: string;
  facility_name: string;
  customer_name: string;
  origin_name: string;
  origin_city: string;
  product_category: string;
  load_weight_kg: number;
  pallet_count: number | null;
  required_dock_type: DockType;
  temperature_control_required: boolean;
  priority_code: Priority;
  requested_date: string | null;
  expected_unload_min: number;
  current_status: ShipmentStatus;
  offer_status: OfferStatus;
  offer_decline_reason: string | null;
  original_eta_ts: string | null;
  latest_eta_ts: string | null;
  planned_departure_ts: string | null;
}

export type TimelineKind =
  | "created"
  | "offered"
  | "assigned"
  | "eta"
  | "appointment"
  | "checkin"
  | "unload"
  | "cancelled"
  | "audit";

export interface TimelineEvent {
  ts: string;
  kind: TimelineKind;
  title: string;
  detail: string | null;
  actor: string | null;
  meta: Record<string, unknown> | null;
}

export interface ShipmentTimeline {
  events: TimelineEvent[];
  threads: { id: string; code: string; status: string }[];
}

export interface AuditRow {
  id: string;
  actor_type: string;
  actor_id: string | null;
  action: string;
  entity: string;
  entity_id: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  created_at: string;
}

export interface SettingRow {
  key: string;
  value: unknown;
  description: string | null;
}

export interface ImportResult {
  dry_run: boolean;
  created: number;
  errors: { row: number; message: string }[];
}
