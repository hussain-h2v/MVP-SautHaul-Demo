export type ProviderKind = "openai" | "anthropic" | "google" | "azure_openai" | "openai_compatible" | "mock";
export type BreakerState = "closed" | "open" | "half_open";
export type ErrorCode = "timeout" | "rate_limit" | "server_error" | "network" | "auth";
export type KeyStrategy = "single" | "round_robin" | "weighted";
export type Capability = "chat" | "tools" | "json" | "vision" | "multilingual";

export interface AiProvider {
  id: string;
  name: string;
  kind: ProviderKind;
  base_url: string | null;
  status: "enabled" | "disabled";
  rate_limit_rpm: number | null;
  allow_pii: boolean;
  last_error: string | null;
  last_checked_at: string | null;
  notes: string | null;
  key_count: number;
  model_count: number;
  breaker: BreakerState;
}

export interface AiKey {
  id: string;
  provider_id: string;
  provider_name: string;
  label: string;
  key_last4: string;
  status: "active" | "disabled" | "failed";
  last_used_at: string | null;
  monthly_budget: number | null;
  weight: number;
  last_error: string | null;
  month_spend: number;
  month_requests: number;
}

export interface AiModel {
  id: string;
  provider_id: string;
  provider_name?: string;
  model_name: string;
  capabilities: Capability[];
  context_window: number | null;
  input_price: number;
  output_price: number;
  status?: string;
}

export interface StepConditions {
  languages?: string[];
  max_input_chars?: number;
  min_input_chars?: number;
}

export interface RouteStep {
  id?: string;
  priority?: number;
  model_id: string;
  model_name?: string;
  provider_name?: string;
  key_id: string | null;
  key_ids: string[];
  key_strategy: KeyStrategy;
  timeout_ms: number;
  max_retries: number;
  temperature: number;
  max_tokens: number;
  conditions: StepConditions;
}

export interface AiRoute {
  task: string;
  description: string | null;
  enabled: boolean;
  fallback_on_refusal: boolean;
  steps: RouteStep[];
}

export interface PathEntry {
  step: number;
  provider: string;
  model: string;
  outcome: string;
  forced?: boolean;
  key_id?: string;
  ms?: number;
}

export interface RunResult {
  text?: string;
  parsed?: unknown;
  provider?: string;
  model?: string;
  tokens_in?: number;
  tokens_out?: number;
  cost?: number;
  latency_ms?: number;
  fallback_depth?: number;
  path: PathEntry[];
  unavailable?: boolean;
  reason?: string;
  used?: { provider: string; model: string } | null;
}

export interface AiHealth {
  kill_switch: boolean;
  providers: { id: string; name: string; status: string; breaker: BreakerState; last_error: string | null }[];
  failed_keys: { id: string; label: string; provider_name: string; last_error: string | null }[];
  tasks: { task: string; state: "ok" | "degraded" | "off" | "unconfigured"; steps: number; healthy_steps: number }[];
}

export interface AiPrompt {
  id: string;
  task: string;
  language: string;
  version: number;
  template: string;
  status: "draft" | "active" | "archived";
  notes: string | null;
  created_at: string;
}

export interface DiffChange {
  type: "add" | "del" | "same";
  text: string;
}

export interface EvalCase {
  id: string;
  language: string;
  text: string;
  expected: { intent: string; delay_minutes?: number | null; eta_time?: string | null };
  source: string;
  reviewed: boolean;
}

export interface EvalRun {
  id: string;
  label: string;
  model_id: string | null;
  status: string;
  total: number;
  correct: number;
  accuracy: number;
  avg_latency_ms: number;
  total_cost: number;
  by_language: Record<string, number>;
  created_at: string;
}

export interface EvalResultRow {
  case_id: string;
  language: string;
  text: string;
  expected: Record<string, unknown>;
  got: Record<string, unknown> | null;
  correct: boolean;
  latency_ms: number;
  error: string | null;
}

export interface EvalCompare {
  runs: EvalRun[];
  differences: {
    case_id: string;
    text: string;
    language: string;
    expected: Record<string, unknown>;
    results: { run_id: string; got: Record<string, unknown> | null; correct: boolean }[];
  }[];
}

export interface UsageRow {
  key: string;
  requests: number;
  tokens_in: number;
  tokens_out: number;
  cost: number;
  p50_ms: number;
  p95_ms: number;
  error_rate: number;
  fallback_rate: number;
}

export interface Usage {
  totals: Omit<UsageRow, "key">;
  rows: UsageRow[];
}

export interface AiBudget {
  id: string;
  scope: "global" | "provider" | "task" | "key";
  scope_id: string | null;
  period: "daily" | "monthly";
  limit_amount: number;
  alert_threshold: number;
  enabled: boolean;
  spent: number;
  percent: number;
  state: "ok" | "alert" | "exhausted";
}

export interface AiLog {
  id: string;
  request_id: string;
  task: string;
  provider: string | null;
  model: string | null;
  tokens_in: number;
  tokens_out: number;
  cost: number;
  latency_ms: number;
  status: string;
  fallback_depth: number;
  error_code: string | null;
  trace_id: string | null;
  path: PathEntry[];
  created_at: string;
  prompt_redacted?: string | null;
  response_redacted?: string | null;
}

export interface AiSafety {
  kill_switch: boolean;
  log_bodies: boolean;
  log_retention_days: number;
  breaker: { threshold: number; window_seconds: number; cooldown_seconds: number };
  tasks: { task: string; enabled: boolean }[];
  providers: { id: string; name: string; allow_pii: boolean }[];
}
