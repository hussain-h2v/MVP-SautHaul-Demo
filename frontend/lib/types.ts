// Hand-written until packages/api-client generates types from the OpenAPI schema.
export type Role = "admin" | "facility_planner" | "coordinator" | "carrier_user";
export type Access = "R" | "W";

export type CapabilityKey =
  | "manage_master"
  | "shipments_write"
  | "docks_slots_rules"
  | "day_schedule"
  | "drivers_vehicles"
  | "assign_driver_vehicle"
  | "shipment_details"
  | "booking_decisions"
  | "escalations_takeover"
  | "ai_management"
  | "ai_insights"
  | "analytics"
  | "audit_log"
  | "system_settings";

export interface Scopes {
  all_facilities: boolean;
  facility_ids: string[];
  carrier_id: string | null;
}

export interface UserOut {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  locale: string;
  scopes: Scopes;
  capabilities: Partial<Record<CapabilityKey, Access>>;
}

export const roleHome: Record<Role, string> = {
  admin: "/admin",
  facility_planner: "/facility",
  coordinator: "/coordinator",
  carrier_user: "/carrier",
};
