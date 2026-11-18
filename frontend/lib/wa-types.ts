export type WaMode = "cloud" | "simulator";

export interface WaStatus {
  configured: boolean;
  mode: WaMode;
  webhook_path: string;
  verify_token_set: boolean;
  app_secret_set: boolean;
  phone_number_id_masked: string | null;
  last_inbound_at: string | null;
  last_outbound_at: string | null;
  pending_events: number;
  failed_events: number;
  failed_deliveries_24h: number;
  templates: { total: number; approved: number; needs_review: number };
}

export type ApprovalStatus = "draft" | "submitted" | "approved" | "rejected";

export interface WaButton {
  id: string;
  title: string;
}

export interface WaTemplate {
  id: string;
  name: string;
  language: string;
  category: string;
  body: string;
  variables: string[];
  buttons: WaButton[];
  approval_status: ApprovalStatus;
  needs_native_review: boolean;
  meta_template_id: string | null;
}

export interface WaFailure {
  id: string;
  created_at: string;
  driver_id: string | null;
  driver_name: string | null;
  to: string | null;
  error: string | null;
  template_name: string | null;
  purpose: string | null;
  text: string | null;
}

export interface WaPage<T> {
  total: number;
  items: T[];
}

export type DeliveryStatus = "received" | "queued" | "sent" | "delivered" | "read" | "failed";

export interface WaMessage {
  id: string;
  wa_message_id: string | null;
  direction: "in" | "out";
  driver_id: string | null;
  driver_name: string | null;
  thread_id: string | null;
  type: string;
  text: string | null;
  language: string | null;
  template_name: string | null;
  delivery_status: DeliveryStatus;
  error: string | null;
  purpose: string | null;
  created_at: string;
}

export interface WaOptIn {
  driver_id: string;
  driver_name: string;
  carrier_name: string;
  whatsapp_number: string | null;
  state: "opted_in" | "opted_out";
  verified: boolean;
  last_event: string | null;
  last_event_at: string | null;
  source: string | null;
}

export interface SimButton {
  id: string;
  title: string;
}

export interface SimRow {
  id: string;
  title: string;
  description?: string;
}

export interface SimMessage {
  id: string;
  direction: "in" | "out";
  kind: "text" | "buttons" | "list" | "template";
  text: string | null;
  buttons: SimButton[];
  rows: SimRow[];
  list_button?: string | null;
  language: string | null;
  purpose: string | null;
  template_name: string | null;
  delivery_status: DeliveryStatus;
  created_at: string;
}

export interface SimSendBody {
  driver_id: string;
  kind: "text" | "button" | "list";
  text?: string;
  button_id?: string;
  list_id?: string;
  title?: string;
}

export interface SimSendResult {
  event_id: string;
  inbound_message_id: string | null;
  replies: SimMessage[];
}

export interface SimDriver {
  id: string;
  code: string;
  driver_name: string;
  carrier_name: string;
  preferred_language: string;
  verified: boolean;
  whatsapp_opt_in: boolean;
  whatsapp_number: string | null;
  active_shipments: number;
}

export interface ThreadInfo {
  id: string;
  code: string;
  driver_id?: string;
  thread_status: string;
  thread_intent: string;
  requires_review: boolean;
  taken_over_by: { id: string; name: string } | null;
  bot_paused: boolean;
}
