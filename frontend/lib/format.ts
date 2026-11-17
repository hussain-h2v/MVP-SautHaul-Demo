const TZ = "Asia/Kolkata";

export function formatDateTime(iso: string | null | undefined, locale = "en"): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat(locale === "hi" ? "hi-IN" : "en-IN", {
    timeZone: TZ,
    dateStyle: "medium",
    timeStyle: "short",
  }).format(d);
}

export function formatDate(iso: string | null | undefined, locale = "en"): string {
  if (!iso) return "—";
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00+05:30` : iso);
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat(locale === "hi" ? "hi-IN" : "en-IN", { timeZone: TZ, dateStyle: "medium" }).format(d);
}

export const LANGUAGES = ["en", "hi", "te", "mr", "gu", "pa", "ta", "kn", "bn"] as const;
