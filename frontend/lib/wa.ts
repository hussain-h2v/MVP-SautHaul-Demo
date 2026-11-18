import type { DeliveryStatus, SimMessage, SimSendBody, WaButton } from "./wa-types";

/** Unique {{placeholders}} in a template body, in order of first appearance. */
export function bodyVariables(body: string): string[] {
  const seen: string[] = [];
  for (const m of body.matchAll(/\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}/g)) if (!seen.includes(m[1])) seen.push(m[1]);
  return seen;
}

export interface VarCheck {
  ok: boolean;
  /** declared but never used in the body */
  unused: string[];
  /** used in the body but not declared */
  unknown: string[];
}

/** Every declared variable must be used and no unknown variable may appear. */
export function validateTemplateVars(body: string, declared: string[]): VarCheck {
  const used = bodyVariables(body);
  const unused = declared.filter((v) => !used.includes(v));
  const unknown = used.filter((v) => !declared.includes(v));
  return { ok: unused.length === 0 && unknown.length === 0, unused, unknown };
}

export const SAMPLE_VALUES: Record<string, string> = {
  slot_code: "SLOT-JAI-019",
  dock_code: "D3",
  facility: "SetuHaul Jaipur DC",
  start: "04 Aug 10:00",
  end: "04 Aug 11:00",
  reason: "Dock maintenance",
  outcome: "confirmed",
  reference: "A1B2C3D4",
  code: "123456",
};

/** Safe preview: only {{variable}} replacement, unknown names show as <name>. */
export function renderPreview(body: string, samples: Record<string, string> = SAMPLE_VALUES): string {
  return body.replace(/\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}/g, (_, name: string) => samples[name] ?? `<${name}>`);
}

export const MAX_BUTTONS = 3;
export const BUTTON_TITLE_MAX = 20;

export function validateButtons(buttons: WaButton[]): string | null {
  if (buttons.length > MAX_BUTTONS) return "tooMany";
  const ids = new Set<string>();
  for (const b of buttons) {
    if (!b.id.trim() || !b.title.trim()) return "empty";
    if (b.title.length > BUTTON_TITLE_MAX) return "tooLong";
    if (ids.has(b.id)) return "duplicate";
    ids.add(b.id);
  }
  return null;
}

/** Languages shown first in the catalogue grid, then any others the server returns. */
export function catalogueLanguages(present: string[]): string[] {
  const first = ["en", "hi", "te"];
  return [...first, ...[...new Set(present)].filter((l) => !first.includes(l)).sort()];
}

export interface Bubble {
  id: string;
  side: "driver" | "bot";
  text: string;
  time: string;
  status: DeliveryStatus | "pending";
  buttons: { id: string; title: string }[];
  rows: { id: string; title: string; description?: string }[];
  listButton: string | null;
  template: string | null;
  language: string | null;
  /** chips are only tappable on the newest bot message */
  tappable: boolean;
}

/** Server message -> chat bubble. Inbound = the driver (right), outbound = the bot (left). */
export function toBubble(m: SimMessage, tappable = false): Bubble {
  const kindText = m.kind === "template" && !m.text ? `[${m.template_name ?? "template"}]` : (m.text ?? "");
  return {
    id: m.id,
    side: m.direction === "in" ? "driver" : "bot",
    text: kindText,
    time: m.created_at,
    status: m.delivery_status,
    buttons: m.direction === "out" ? m.buttons ?? [] : [],
    rows: m.direction === "out" ? m.rows ?? [] : [],
    listButton: m.list_button ?? null,
    template: m.template_name,
    language: m.language,
    tappable: tappable && m.direction === "out" && ((m.buttons?.length ?? 0) > 0 || (m.rows?.length ?? 0) > 0),
  };
}

export function toBubbles(messages: SimMessage[]): Bubble[] {
  let lastOut = -1;
  messages.forEach((m, i) => {
    if (m.direction === "out") lastOut = i;
  });
  return messages.map((m, i) => toBubble(m, i === lastOut));
}

/** A pending bubble for the driver's own just-sent message (optimistic UI, replaced by the server copy). */
export function pendingBubble(text: string, now = new Date()): Bubble {
  return { id: `pending-${now.getTime()}`, side: "driver", text, time: now.toISOString(), status: "pending", buttons: [], rows: [], listButton: null, template: null, language: null, tappable: false };
}

/** What a phone sends when a chip is tapped: the id plus the visible title. */
export function quickReplyPayload(driverId: string, kind: "button" | "list", id: string, title: string): SimSendBody {
  return kind === "button" ? { driver_id: driverId, kind, button_id: id, title } : { driver_id: driverId, kind, list_id: id, title };
}

export function textPayload(driverId: string, text: string): SimSendBody {
  return { driver_id: driverId, kind: "text", text: text.trim() };
}

export const QUICK_TESTS = [
  { key: "breakdown", text: "Truck breakdown, 2 hours late" },
  { key: "hindi", text: "गाड़ी 2 घंटे लेट है" },
  { key: "options", text: "What slots are available after 4 pm?" },
  { key: "arrived", text: "I reached the gate" },
  { key: "safety", text: "accident ho gaya" },
  { key: "stop", text: "STOP" },
] as const;

/** Rough script-based hint of the language the driver wrote in (the server decides the real reply language). */
export function detectLanguageHint(text: string): string | null {
  if (/[ऀ-ॿ]/.test(text)) return "hi";
  if (/[ఀ-౿]/.test(text)) return "te";
  if (/[஀-௿]/.test(text)) return "ta";
  if (/[઀-૿]/.test(text)) return "gu";
  if (/[਀-੿]/.test(text)) return "pa";
  if (/[ಀ-೿]/.test(text)) return "kn";
  if (/[ঀ-৿]/.test(text)) return "bn";
  return /[A-Za-z]/.test(text) ? "en" : null;
}

const TICKS: Record<string, { ticks: 0 | 1 | 2; read: boolean }> = {
  pending: { ticks: 0, read: false },
  queued: { ticks: 0, read: false },
  received: { ticks: 1, read: false },
  sent: { ticks: 1, read: false },
  delivered: { ticks: 2, read: false },
  read: { ticks: 2, read: true },
  failed: { ticks: 0, read: false },
};

export function deliveryTicks(status: string): { ticks: 0 | 1 | 2; read: boolean } {
  return TICKS[status] ?? { ticks: 0, read: false };
}

export const STATUS_TONE: Record<string, "neutral" | "accent" | "success" | "warning" | "danger"> = {
  received: "neutral",
  queued: "neutral",
  sent: "accent",
  delivered: "success",
  read: "success",
  failed: "danger",
  draft: "neutral",
  submitted: "warning",
  approved: "success",
  rejected: "danger",
};
