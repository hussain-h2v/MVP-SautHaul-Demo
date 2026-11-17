"use client";

import { AlertTriangle, ArrowRight, Check, CircleSlash, Loader2, X } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";
import { Badge, Skeleton } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { pathNodes } from "@/lib/ai";
import type { BreakerState, PathEntry, RunResult } from "@/lib/ai-types";
import { cn } from "@/lib/utils";

/** Translate `${prefix}.${value}` when the key exists, else show the raw value. */
export function useEnum(prefix: string) {
  const t = useTranslations("ai");
  return (value: string) => (t.has(`${prefix}.${value}` as never) ? t(`${prefix}.${value}` as never) : value);
}

export function QueryState({
  isLoading,
  error,
  empty,
  onRetry,
  children,
}: {
  isLoading: boolean;
  error: unknown;
  empty?: boolean;
  onRetry?: () => void;
  children: React.ReactNode;
}) {
  const t = useTranslations("ai");
  if (isLoading)
    return (
      <div role="status" aria-label={t("g.loading")} className="space-y-3">
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-10 w-2/3" />
      </div>
    );
  if (error)
    return (
      <div role="alert" className="flex items-center justify-between gap-3 rounded-md border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger">
        <span>{t("g.error")}</span>
        {onRetry && (
          <Button size="sm" variant="outline" onClick={onRetry}>
            {t("g.retry")}
          </Button>
        )}
      </div>
    );
  if (empty) return <p className="rounded-md border border-dashed border-border px-4 py-8 text-center text-sm text-muted">{t("g.empty")}</p>;
  return <>{children}</>;
}

/** Accessible on/off switch (role=switch, keyboard operable). */
export function Switch({
  checked,
  onChange,
  label,
  disabled,
  id,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  disabled?: boolean;
  id?: string;
}) {
  return (
    <button
      id={id}
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative inline-flex h-6 w-11 shrink-0 items-center rounded-full border border-border transition-colors disabled:opacity-60",
        checked ? "bg-accent" : "bg-background",
      )}
    >
      <span className={cn("inline-block size-4 rounded-full bg-white shadow transition-transform", checked ? "translate-x-6" : "translate-x-1")} />
    </button>
  );
}

export function BreakerBadge({ state }: { state: BreakerState }) {
  const e = useEnum("breaker");
  const tone = state === "closed" ? "success" : state === "open" ? "danger" : "warning";
  const Icon = state === "closed" ? Check : state === "open" ? X : AlertTriangle;
  return (
    <Badge tone={tone} className="gap-1">
      <Icon className="size-3" aria-hidden="true" />
      {e(state)}
    </Badge>
  );
}

const nodeStyle = {
  ok: "border-success/50 bg-accent-soft text-foreground",
  failed: "border-danger/50 bg-danger/10 text-foreground",
  skipped: "border-border bg-background text-muted",
} as const;

/** The router's fallback path as a chain. Each node always carries a text code and an icon, never colour alone. */
export function PathChain({ path }: { path: PathEntry[] }) {
  const t = useTranslations("ai");
  const nodes = pathNodes(path);
  if (!nodes.length) return <p className="text-sm text-muted">—</p>;
  return (
    <ol className="flex flex-wrap items-stretch gap-2" aria-label={t("lg.path")}>
      {nodes.map((n, i) => {
        const Icon = n.tone === "ok" ? Check : n.tone === "failed" ? X : CircleSlash;
        return (
          <li key={`${n.step}-${i}`} className="flex items-center gap-2">
            {i > 0 && <ArrowRight className="size-4 text-muted" aria-hidden="true" />}
            <div className={cn("rounded-lg border px-3 py-2 text-sm", nodeStyle[n.tone])}>
              <div className="flex items-center gap-1.5 font-medium">
                <Icon className="size-4" aria-hidden="true" />
                <span>
                  #{n.step} {n.label}
                </span>
              </div>
              <div className="mt-0.5 text-xs">
                <span className="font-mono">{n.code}</span>
                <span className="text-muted">
                  {" · "}
                  {t(`outcome.${n.tone}` as never)}
                  {n.forced ? ` · ${t("outcome.forced")}` : ""}
                  {n.repaired ? ` · ${t("outcome.repaired")}` : ""}
                </span>
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

export function RunResultView({ result }: { result: RunResult }) {
  const t = useTranslations("ai");
  return (
    <div aria-live="polite" className="space-y-3">
      {result.unavailable ? (
        <div role="alert" className="rounded-md border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger">
          {t("ov.unavailable", { reason: result.reason ?? "?" })}
        </div>
      ) : (
        <>
          <p className="text-sm font-medium">
            {t("ov.answeredBy", { model: result.model ?? "?", provider: result.provider ?? "?", depth: result.fallback_depth ?? 0 })}
          </p>
          {result.text && <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-md border border-border bg-background p-3 text-sm">{result.text}</pre>}
          {result.parsed !== undefined && result.parsed !== null && (
            <pre className="max-h-48 overflow-auto rounded-md border border-border bg-background p-3 font-mono text-xs">{JSON.stringify(result.parsed, null, 2)}</pre>
          )}
          <p className="text-xs text-muted">
            {result.latency_ms} ms · {result.tokens_in}/{result.tokens_out} tokens
          </p>
        </>
      )}
      <PathChain path={result.path} />
    </div>
  );
}

export function Busy({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center gap-2">
      <Loader2 className="size-4 animate-spin" aria-hidden="true" />
      {label}
    </span>
  );
}

export function SectionHeader({ title, description, actions }: { title: string; description?: string; actions?: React.ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 className="text-xl font-semibold tracking-tight">{title}</h2>
        {description && <p className="mt-1 max-w-3xl text-sm text-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export function DataTableLite({ head, children, caption }: { head: string[]; children: React.ReactNode; caption?: string }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-border bg-surface">
      <table className="w-full text-left text-sm">
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead className="border-b border-border bg-background text-xs uppercase tracking-wide text-muted">
          <tr>
            {head.map((h, i) => (
              <th key={i} scope="col" className="whitespace-nowrap px-4 py-2.5 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">{children}</tbody>
      </table>
    </div>
  );
}
