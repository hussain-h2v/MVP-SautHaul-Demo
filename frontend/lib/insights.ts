import { useQuery } from "@tanstack/react-query";
import { api } from "./api";

export type RangeKey = "1d" | "3d" | "7d" | "3w" | "1m";
export const RANGES: RangeKey[] = ["1d", "3d", "7d", "3w", "1m"];
export type ViewKey = "network" | "facility" | "coordinator" | "carrier";

export interface Kpi {
  value: number;
  previous: number;
  change: number | null;
  good_when_up: boolean | null;
}

export interface SeriesPoint {
  bucket: string;
  arrivals: number;
  late: number;
  loads: number;
  requests: number;
  escalations: number;
  delay_reports: number;
  no_shows: number;
  available_min: number;
  booked_min: number;
  utilisation_pct: number;
  avg_wait_min: number;
}

export interface ShareRow {
  key: string;
  count: number;
  share: number;
  avg_delay_min?: number;
  avg_resolution_min?: number;
}

export interface InsightsView {
  view: ViewKey;
  scope: string;
  period: { range: string; from: string; to: string; bucket: "hour" | "day"; timezone: string };
  kpis: Record<string, Kpi>;
  extra: Record<string, number>;
  series: SeriesPoint[];
  tables: {
    by_dock?: { facility: string; dock: string; type: string; available_min: number; booked_min: number; utilisation_pct: number }[];
    heatmap?: { dow: number; hour: number; available_min: number; booked_min: number; utilisation_pct: number }[];
    by_facility?: { facility: string; available_min: number; booked_min: number; utilisation_pct: number }[];
    dock_events?: { facility: string; dock: string; type: string; events: number; hours: number }[];
    delay_causes?: ShareRow[];
    escalation_reasons?: ShareRow[];
    request_mix?: ShareRow[];
    by_driver?: { code: string; driver: string; trips: number; late: number; late_rate: number; avg_late_min: number; delay_reports: number }[];
    by_lane?: { origin: string; facility: string; trips: number; late: number; late_rate: number; avg_late_min: number; avg_wait_min: number }[];
  };
  ai_spend?: { today: string; today_requests: number; month_to_date: string; projected_month: string; currency: string };
}

export interface Narrative {
  task: string;
  ai_available: boolean;
  text: string | null;
  model: string | null;
  cached: boolean;
  generated_at: string;
  language: string;
}

export interface Proposal {
  facility: string;
  date: string;
  movable: number;
  fixed_slots?: number;
  writes: number;
  note?: string;
  better_than_current?: boolean;
  saved_weighted_wait?: number;
  rule?: string;
  scorecards: Record<"current" | "fcfs" | "proposed", { placed: number; unplaced: number; total_wait_min: number; avg_wait_min: number; max_wait_min: number; priority_weighted_wait: number; high_priority_wait_min: number; moved: number }>;
  moves: { shipment: string; carrier: string | null; priority: string; eta: string; from_dock: string; from_start: string; to_dock: string | null; to_start: string | null; wait_before_min: number | null; wait_after_min: number | null; changes: boolean; placed: boolean }[];
}

export function qs(params: Record<string, string | number | null | undefined>): string {
  const sp = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== "" && v !== null && v !== undefined) sp.set(k, String(v));
  });
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export function useInsightsView(view: ViewKey, range: RangeKey, extra: Record<string, string | null | undefined> = {}, enabled = true) {
  const path = `/analytics/views/${view}${qs({ range, ...extra })}`;
  return useQuery<InsightsView>({ queryKey: ["insights", path], queryFn: () => api<InsightsView>(path), enabled, refetchInterval: 60_000 });
}

export function useNarrative(view: ViewKey, range: RangeKey, lang: string, extra: Record<string, string | null | undefined> = {}, enabled = true) {
  const path = `/insights/narrative${qs({ view, range, lang, ...extra })}`;
  return useQuery<Narrative>({ queryKey: ["insights", path], queryFn: () => api<Narrative>(path), enabled, staleTime: 5 * 60_000 });
}

/** Weekday names for the ISO day numbers 1..7 (Monday first). */
export const WEEKDAYS = [1, 2, 3, 4, 5, 6, 7];

/** Colour class for a KPI change: green when the move is good, red when bad, neutral when the metric has no good direction. */
export function changeTone(change: number | null, goodWhenUp: boolean | null): "good" | "bad" | "neutral" {
  if (change === null || change === 0 || goodWhenUp === null) return "neutral";
  return (change > 0) === goodWhenUp ? "good" : "bad";
}

/** Heat colour: 0 to 100 per cent mapped onto an opacity of the accent colour. */
export function heatOpacity(pct: number): number {
  return Math.round((0.12 + Math.min(Math.max(pct, 0), 100) / 100 * 0.88) * 100) / 100;
}

export function formatKpi(key: string, v: number): string {
  if (key.endsWith("_pct") || key.endsWith("_rate")) return `${v.toFixed(1)}%`;
  if (key.endsWith("_min")) return `${Math.round(v)} min`;
  if (key === "lost_hours") return `${v.toFixed(1)} h`;
  return Number.isInteger(v) ? v.toLocaleString() : v.toFixed(1);
}
