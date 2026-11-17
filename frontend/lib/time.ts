export const DEFAULT_TZ = "Asia/Kolkata";

function parts(date: Date, tz: string): Record<string, number> {
  const fmt = new Intl.DateTimeFormat("en-GB", {
    timeZone: tz,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  });
  const out: Record<string, number> = {};
  for (const p of fmt.formatToParts(date)) if (p.type !== "literal") out[p.type] = Number(p.value);
  return out;
}

/** "YYYY-MM-DD" of an instant in the given zone. */
export function isoDateInTz(date: Date | string, tz = DEFAULT_TZ): string {
  const p = parts(typeof date === "string" ? new Date(date) : date, tz);
  return `${p.year}-${String(p.month).padStart(2, "0")}-${String(p.day).padStart(2, "0")}`;
}

export function todayIn(tz = DEFAULT_TZ, now: Date = new Date()): string {
  return isoDateInTz(now, tz);
}

export function addDays(iso: string, n: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

/** "HH:MM" (24h) of an instant in the zone; "—" for empty/invalid. */
export function hhmm(iso: string | null | undefined, tz = DEFAULT_TZ): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const p = parts(d, tz);
  return `${String(p.hour).padStart(2, "0")}:${String(p.minute).padStart(2, "0")}`;
}

/** Minutes between local midnight of `dateIso` (in tz) and the instant. May be <0 or >1440 across days. */
export function minutesFromDayStart(iso: string, dateIso: string, tz = DEFAULT_TZ): number {
  const p = parts(new Date(iso), tz);
  const [y, m, d] = dateIso.split("-").map(Number);
  return (Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute) - Date.UTC(y, m - 1, d)) / 60000;
}

export function parseHHMM(v: string): number {
  const [h, m] = v.split(":").map(Number);
  return h * 60 + (m || 0);
}

/** Convert a `datetime-local` value ("YYYY-MM-DDTHH:mm") entered in zone tz to an ISO instant. */
export function zonedToIso(local: string, tz = DEFAULT_TZ): string {
  const [datePart, timePart = "00:00"] = local.split("T");
  const [y, mo, d] = datePart.split("-").map(Number);
  const [h, mi] = timePart.split(":").map(Number);
  const asUtc = Date.UTC(y, mo - 1, d, h, mi);
  let guess = asUtc;
  for (let i = 0; i < 2; i++) {
    const p = parts(new Date(guess), tz);
    const shown = Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute);
    guess += asUtc - shown;
  }
  return new Date(guess).toISOString();
}

export function minutesUntil(iso: string, now: number): number {
  return Math.floor((new Date(iso).getTime() - now) / 60000);
}

/** "mm:ss" countdown, or "0:00" once expired. */
export function countdown(iso: string, now: number): string {
  const s = Math.max(0, Math.floor((new Date(iso).getTime() - now) / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
