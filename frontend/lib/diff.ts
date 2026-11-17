export interface FieldChange {
  key: string;
  before: unknown;
  after: unknown;
  kind: "added" | "removed" | "changed";
}

/** Field-level diff of two audit snapshots. Unchanged fields are omitted. */
export function diffObjects(before: Record<string, unknown> | null, after: Record<string, unknown> | null): FieldChange[] {
  const b = before ?? {};
  const a = after ?? {};
  const keys = Array.from(new Set([...Object.keys(b), ...Object.keys(a)])).sort();
  const out: FieldChange[] = [];
  for (const key of keys) {
    const inB = key in b && b[key] !== null && b[key] !== undefined;
    const inA = key in a && a[key] !== null && a[key] !== undefined;
    if (JSON.stringify(b[key] ?? null) === JSON.stringify(a[key] ?? null)) continue;
    out.push({ key, before: b[key], after: a[key], kind: !inB ? "added" : !inA ? "removed" : "changed" });
  }
  return out;
}

export function formatValue(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "string") return v;
  return JSON.stringify(v);
}
