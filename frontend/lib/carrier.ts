import type { Problem, SlotChangeKind } from "./carrier-types";

/** Translator shape (next-intl's `t` satisfies it). */
export type Tr = { (key: string, values?: Record<string, string | number>): string; has: (key: string) => boolean };

/** Languages a driver can be served in on WhatsApp (native names). */
export const LANGUAGE_OPTIONS = [
  { code: "en", native: "English" },
  { code: "hi", native: "हिन्दी" },
  { code: "te", native: "తెలుగు" },
  { code: "mr", native: "मराठी" },
  { code: "gu", native: "ગુજરાતી" },
  { code: "pa", native: "ਪੰਜਾਬੀ" },
  { code: "ta", native: "தமிழ்" },
  { code: "kn", native: "ಕನ್ನಡ" },
  { code: "bn", native: "বাংলা" },
] as const;

export function languageLabel(code: string | null | undefined): string {
  if (!code) return "—";
  const found = LANGUAGE_OPTIONS.find((l) => l.code === code.toLowerCase());
  return found ? `${found.native} (${found.code.toUpperCase()})` : code.toUpperCase();
}

/** Blocking reasons a vehicle/driver cannot take a shipment. Strings: carrier.assign.codes.<CODE>. */
export const ASSIGN_PROBLEM_CODES = [
  "VEHICLE_NOT_REFRIGERATED",
  "VEHICLE_NOT_HEAVY",
  "LOAD_EXCEEDS_CAPACITY",
  "VEHICLE_TYPE_NOT_ALLOWED",
  "DRIVER_INACTIVE",
  "VEHICLE_INACTIVE",
] as const;

/** Non-blocking warnings. */
export const ASSIGN_WARNING_CODES = ["DRIVER_ON_ANOTHER_SHIPMENT", "DRIVER_NOT_VERIFIED"] as const;

export const ASSIGN_CODES = [...ASSIGN_PROBLEM_CODES, ...ASSIGN_WARNING_CODES] as const;

/** Human text for an assignment problem/warning: our translation when we know the code, else the server's message. */
export function assignmentMessage(t: Tr, p: Problem): string {
  const key = `assign.codes.${p.code}`;
  return t.has(key) ? t(key) : p.message || p.code;
}

/** The assign button may be pressed only when both are chosen, the check has run and nothing blocks. */
export function canSubmitAssignment(
  driverId: string,
  vehicleId: string,
  check: { problems: Problem[] } | null | undefined,
): boolean {
  return !!driverId && !!vehicleId && !!check && check.problems.length === 0;
}

/** Group items by Asia/Kolkata calendar day, newest day first, keeping each day's input order. */
export function groupByDay<T>(items: T[], ts: (item: T) => string, tz = "Asia/Kolkata"): { day: string; items: T[] }[] {
  const fmt = new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit" });
  const map = new Map<string, T[]>();
  for (const item of items) {
    const d = new Date(ts(item));
    const day = Number.isNaN(d.getTime()) ? "unknown" : fmt.format(d);
    const list = map.get(day);
    if (list) list.push(item);
    else map.set(day, [item]);
  }
  return [...map.entries()].sort((a, b) => (a[0] < b[0] ? 1 : a[0] > b[0] ? -1 : 0)).map(([day, list]) => ({ day, items: list }));
}

export type Tone = "neutral" | "accent" | "success" | "warning" | "danger";

export const SLOT_CHANGE_KINDS: SlotChangeKind[] = [
  "confirmed",
  "pending_confirmation",
  "held",
  "suggested",
  "rejected",
  "cancelled",
  "replaced",
  "no_show",
  "escalated",
];

export function slotChangeTone(kind: SlotChangeKind): Tone {
  switch (kind) {
    case "confirmed":
      return "success";
    case "pending_confirmation":
    case "held":
    case "suggested":
      return "warning";
    case "rejected":
    case "cancelled":
    case "no_show":
    case "escalated":
      return "danger";
    default:
      return "neutral";
  }
}

/** "99+" cap for the bell badge; "" when nothing is unread. */
export function badgeCount(unread: number): string {
  if (unread <= 0) return "";
  return unread > 99 ? "99+" : String(unread);
}

/** Where the "View all" link of the bell goes for each portal. */
export function notificationsHref(slug: string): string {
  return `/${slug}/notifications`;
}

/** Notification types we have a friendlier label for (messages: notifications.types.<type>). */
export const NOTIFICATION_TYPES = [
  "shipment.offered",
  "shipment.reassigned",
  "slot.confirmed",
  "slot.suggested",
  "slot.held",
  "slot.rejected",
  "slot.cancelled",
  "escalation.created",
  "replan.requested",
  "driver.unverified",
  "delay.reported",
] as const;

export function toCsvFilename(kind: string, from: string, to: string): string {
  return `carrier-${kind}-${from}-${to}.csv`;
}

/** Pick known keys out of a query string such as "?verified=false&x=1" (client only; "" on the server). */
export function pickParams(search: string, keys: readonly string[]): Record<string, string> {
  const sp = new URLSearchParams(search);
  const out: Record<string, string> = {};
  for (const k of keys) {
    const v = sp.get(k);
    if (v) out[k] = v;
  }
  return out;
}

export function initialFiltersFromUrl(keys: readonly string[]): Record<string, string> {
  return typeof window === "undefined" ? {} : pickParams(window.location.search, keys);
}

/** next-intl treats "." in a message key as a path separator, so notification types map to snake keys. */
export function notificationTypeKey(type: string): string {
  return type.replace(/\./g, "_");
}
