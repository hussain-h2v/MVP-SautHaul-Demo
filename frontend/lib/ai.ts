import type { AiBudget, EvalCompare, EvalRun, PathEntry, RouteStep } from "./ai-types";

export const AI_TASKS = [
  "driver_chat",
  "intent_classify",
  "translate",
  "summarise",
  "driver_insight",
  "dock_insight",
  "coordinator_suggestion",
  "transcribe",
] as const;

export const ERROR_CODES = ["timeout", "rate_limit", "server_error", "network", "auth"] as const;
export const CAPABILITIES = ["chat", "tools", "json", "vision", "multilingual"] as const;
export const PROVIDER_KINDS = ["openai", "anthropic", "google", "azure_openai", "openai_compatible", "mock"] as const;

/** Move step `from` to position `to` and return a new array (priorities are implied by order). */
export function moveStep<T>(steps: T[], from: number, to: number): T[] {
  if (from === to || from < 0 || to < 0 || from >= steps.length || to >= steps.length) return steps;
  const next = steps.slice();
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item);
  return next;
}

export function removeStep<T>(steps: T[], index: number): T[] {
  return steps.filter((_, i) => i !== index);
}

/** Position label used in the UI: primary, secondary, tertiary, then "step N". */
export function stepRole(index: number): "primary" | "secondary" | "tertiary" | "other" {
  return (["primary", "secondary", "tertiary"] as const)[index] ?? "other";
}

export function blankStep(modelId: string): RouteStep {
  return {
    model_id: modelId,
    key_id: null,
    key_ids: [],
    key_strategy: "single",
    timeout_ms: 20000,
    max_retries: 1,
    temperature: 0.2,
    max_tokens: 800,
    conditions: {},
  };
}

/** Steps as sent to PUT /routes/{task}: server-only fields stripped, order defines priority. */
export function stepsPayload(steps: RouteStep[]) {
  return steps.map((s) => ({
    model_id: s.model_id,
    key_id: s.key_id ?? null,
    key_ids: s.key_ids,
    key_strategy: s.key_strategy,
    timeout_ms: s.timeout_ms,
    max_retries: s.max_retries,
    temperature: s.temperature,
    max_tokens: s.max_tokens,
    conditions: s.conditions,
  }));
}

export function sameSteps(a: RouteStep[], b: RouteStep[]): boolean {
  return JSON.stringify(stepsPayload(a)) === JSON.stringify(stepsPayload(b));
}

export type BudgetState = AiBudget["state"];

/** State derived from spend and threshold (used for optimistic display; the server value wins when present). */
export function budgetState(spent: number, limit: number, threshold: number): BudgetState {
  if (limit <= 0) return "ok";
  const ratio = spent / limit;
  if (ratio >= 1) return "exhausted";
  return ratio >= threshold ? "alert" : "ok";
}

export function formatPercent(spent: number, limit: number): string {
  if (limit <= 0) return "0%";
  return `${Math.min(999, Math.round((spent / limit) * 100))}%`;
}

export function formatMoney(v: number | string | null | undefined): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  if (n === 0) return "$0";
  if (n < 0.01) return `$${n.toFixed(6)}`;
  return n < 1 ? `$${n.toFixed(4)}` : `$${n.toFixed(2)}`;
}

export function formatRate(v: number): string {
  return `${(v * 100).toFixed(v > 0 && v < 0.1 ? 1 : 0)}%`;
}

export type PathTone = "ok" | "failed" | "skipped";

export interface PathNode {
  step: number;
  label: string;
  tone: PathTone;
  code: string;
  forced: boolean;
  repaired: boolean;
}

/** Turn a router `path` into display nodes. The text code is always present so status is never colour-only. */
export function pathNodes(path: PathEntry[]): PathNode[] {
  return path.map((p) => {
    const [kind, code = ""] = p.outcome.split(":");
    const tone: PathTone = kind === "ok" ? "ok" : kind === "skipped" ? "skipped" : "failed";
    return {
      step: p.step,
      label: `${p.provider} / ${p.model}`,
      tone,
      code: tone === "ok" ? "ok" : code || kind,
      forced: !!p.forced,
      repaired: !!(p as PathEntry & { repaired?: boolean }).repaired,
    };
  });
}

export function pathSummary(path: PathEntry[]): string {
  const nodes = pathNodes(path);
  return nodes.map((n) => `${n.label} (${n.code})`).join(" → ");
}

export interface RunDelta {
  accuracy: number;
  avg_latency_ms: number;
  total_cost: number;
}

/** Change from the first run (baseline) to each other run; positive accuracy = better. */
export function compareDeltas(runs: EvalRun[]): RunDelta[] {
  if (runs.length === 0) return [];
  const base = runs[0];
  return runs.map((r) => ({
    accuracy: round(r.accuracy - base.accuracy, 4),
    avg_latency_ms: r.avg_latency_ms - base.avg_latency_ms,
    total_cost: round(r.total_cost - base.total_cost, 6),
  }));
}

function round(n: number, d: number) {
  const f = 10 ** d;
  return Math.round(n * f) / f;
}

/** Rows for the per-language chart: one object per language with one accuracy column per run. */
export function languageChartData(runs: EvalRun[]): Record<string, string | number>[] {
  const langs = Array.from(new Set(runs.flatMap((r) => Object.keys(r.by_language)))).sort();
  return langs.map((lang) => {
    const row: Record<string, string | number> = { language: lang };
    runs.forEach((r) => {
      row[r.label || r.id.slice(0, 6)] = Math.round((r.by_language[lang] ?? 0) * 100);
    });
    return row;
  });
}

/** Cases where runs disagree about correctness, for the "differing cases" table. */
export function disagreementCount(c: EvalCompare): number {
  return c.differences.filter((d) => new Set(d.results.map((r) => r.correct)).size > 1).length;
}

export function relativeDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

/** Colour-blind-safe categorical palette (Okabe-Ito). */
export const PALETTE = ["#0072B2", "#E69F00", "#009E73", "#CC79A7", "#D55E00", "#56B4E9", "#F0E442", "#000000"];

/** {{variable}} placeholders found in a prompt template (deduplicated, in order of first use). */
export function templateVariables(template: string): string[] {
  return Array.from(new Set(Array.from(template.matchAll(/\{\{\s*([a-zA-Z_][\w.]*)\s*\}\}/g)).map((m) => m[1])));
}
