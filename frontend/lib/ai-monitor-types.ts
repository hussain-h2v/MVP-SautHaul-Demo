export type RangeKey = "1d" | "3d" | "7d" | "3w" | "1m" | "custom";

export interface Agg {
  requests: number;
  ok: number;
  failed: number;
  tokens_in: number;
  tokens_out: number;
  cost: string;
  avg_cost: string;
  avg_ms: number;
  p50_ms: number;
  p95_ms: number;
  p99_ms: number;
  max_ms: number;
  error_rate: number;
  fallback_rate: number;
}

export interface CallRow {
  id: string;
  request_id: string;
  task: string;
  model: string | null;
  cost: string;
  latency_ms: number;
  tokens_in: number;
  tokens_out: number;
  status: string;
  created_at: string;
}

export interface Monitoring {
  period: { range: string; from: string; to: string; bucket: "hour" | "day"; timezone: string };
  kpis: Agg;
  previous: Agg;
  change: { cost: number | null; requests: number | null; avg_ms: number | null; error_rate: number | null };
  spend: {
    today: { cost: string; requests: number };
    last_7d: { cost: string; requests: number };
    month_to_date: { cost: string; requests: number };
    projected_month: string;
    month: string;
  };
  series: (Agg & { bucket: string })[];
  daily: (Agg & { bucket: string })[];
  by_model: (Agg & { key: string; cost_share: number })[];
  by_provider: (Agg & { key: string; cost_share: number })[];
  by_task: (Agg & { key: string; cost_share: number })[];
  top_cost: CallRow[];
  top_slow: CallRow[];
  facets: { tasks: string[]; providers: string[]; models: string[] };
}

export interface LogItem {
  id: string;
  request_id: string;
  task: string;
  provider: string | null;
  model: string | null;
  tokens_in: number;
  tokens_out: number;
  cost: string;
  latency_ms: number;
  status: string;
  fallback_depth: number;
  error_code: string | null;
  trace_id: string | null;
  created_at: string;
}

export interface LogPage {
  total: number;
  page_cost: string;
  page_tokens_in: number;
  page_tokens_out: number;
  items: LogItem[];
}

export interface Attempt {
  n: number;
  step: number | null;
  provider: string | null;
  model: string | null;
  outcome: "success" | "error" | "skipped" | "not_reached";
  detail: string | null;
  ms: number | null;
  starts_at_ms: number | null;
  key_id: string | null;
  forced: boolean;
  repaired: boolean;
}

export interface Trace extends LogItem {
  prompt_redacted: string | null;
  response_redacted: string | null;
  tokens_total: number;
  pricing: { currency: string; unit: string; input_price: string; output_price: string; input_cost: string; output_cost: string; total_cost: string; priced: boolean };
  key: { id: string | null; label: string | null; last4: string | null };
  attempts: Attempt[];
  final_outcome: "answered" | "blocked" | "unavailable";
  used_fallback: boolean;
  tokens_per_second: number | null;
  same_trace: { id: string; task: string; model: string | null; status: string; cost: string; created_at: string }[];
  bodies_stored: boolean;
}

export interface MapItem {
  task: string;
  status: "wired" | "planned" | "reserved";
  title: string;
  portal: string;
  where: string;
  trigger: string;
  input: string;
  output: string;
  affects: string;
  cannot: string;
  fallback: string;
  route_enabled: boolean;
  route_steps: number;
  last_30d: { requests: number; cost: string; avg_ms: number; error_rate: number; fallbacks: number; last_used: string | null };
}

export interface UsageMap {
  items: MapItem[];
  guards: string[];
  admin_tools: { name: string; where: string; note: string }[];
  flow: string[];
}
