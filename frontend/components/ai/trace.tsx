"use client";

import { Check, CircleSlash, Copy, X } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";
import { toast } from "sonner";
import { QueryState, useEnum } from "@/components/ai/common";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { formatMoney } from "@/lib/ai";
import type { Attempt, Trace } from "@/lib/ai-monitor-types";
import { useAi } from "@/lib/ai-api";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

export const statusTone = { ok: "success", failed: "danger", disabled: "neutral" } as const;

function Tile({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="rounded-lg border border-border bg-background px-3 py-2">
      <p className="text-[11px] font-medium uppercase tracking-wide text-muted">{label}</p>
      <p className="mt-0.5 text-lg font-semibold leading-tight">{value}</p>
      {hint && <p className="text-xs text-muted">{hint}</p>}
    </div>
  );
}

const barTone = {
  success: "bg-success",
  error: "bg-danger",
  skipped: "bg-muted/50",
  not_reached: "bg-muted/30",
} as const;

function Waterfall({ attempts, total }: { attempts: Attempt[]; total: number }) {
  const t = useTranslations("ai");
  const err = useEnum("err");
  const span = Math.max(total, attempts.reduce((m, a) => Math.max(m, (a.starts_at_ms ?? 0) + (a.ms ?? 0)), 0), 1);
  if (!attempts.length) return <p className="text-sm text-muted">{t("tr.noAttempts")}</p>;
  return (
    <ol className="space-y-2" aria-label={t("tr.timeline")}>
      {attempts.map((a) => {
        const Icon = a.outcome === "success" ? Check : a.outcome === "error" ? X : CircleSlash;
        const left = ((a.starts_at_ms ?? 0) / span) * 100;
        const width = a.ms ? Math.max(2, (a.ms / span) * 100) : 1.5;
        return (
          <li key={a.n} className="rounded-lg border border-border bg-background p-3">
            <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
              <div className="flex items-center gap-2">
                <Icon className={cn("size-4", a.outcome === "success" ? "text-success" : a.outcome === "error" ? "text-danger" : "text-muted")} aria-hidden="true" />
                <span className="font-medium">
                  {t("tr.step", { n: a.step ?? a.n })} · {a.model ?? "—"}
                </span>
                <span className="text-xs text-muted">{a.provider}</span>
              </div>
              <div className="flex items-center gap-2 text-xs">
                <Badge tone={a.outcome === "success" ? "success" : a.outcome === "error" ? "danger" : "neutral"}>{t(`tr.o.${a.outcome}`)}</Badge>
                {a.detail && <code className="rounded bg-surface px-1.5 py-0.5">{err(a.detail)}</code>}
                {a.forced && <span className="text-muted">{t("outcome.forced")}</span>}
                {a.repaired && <span className="text-muted">{t("outcome.repaired")}</span>}
              </div>
            </div>
            <div className="mt-2 h-2.5 w-full rounded-full bg-surface" aria-hidden="true">
              <div className={cn("h-2.5 rounded-full", barTone[a.outcome])} style={{ marginLeft: `${Math.min(left, 98)}%`, width: `${Math.min(width, 100 - Math.min(left, 98))}%` }} />
            </div>
            <p className="mt-1 text-xs text-muted">
              {a.ms != null ? t("tr.ms", { ms: a.ms, at: a.starts_at_ms ?? 0 }) : t("tr.notCalled")}
            </p>
          </li>
        );
      })}
    </ol>
  );
}

function Code({ label, text }: { label: string; text: string }) {
  const t = useTranslations("ai");
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      toast.success(t("g.copied"));
    } catch {
      toast.error(t("g.error"));
    }
  };
  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <h4 className="text-sm font-medium">{label}</h4>
        <Button size="sm" variant="ghost" onClick={copy} aria-label={`${t("g.copy")} ${label}`}>
          <Copy className="size-3.5" aria-hidden="true" />
          {t("g.copy")}
        </Button>
      </div>
      <pre className="max-h-56 overflow-auto whitespace-pre-wrap break-words rounded-md border border-border bg-background p-3 text-xs">{text}</pre>
    </div>
  );
}

function Id({ label, value }: { label: string; value: string | null }) {
  const t = useTranslations("ai");
  const copy = async () => {
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
      toast.success(t("g.copied"));
    } catch {
      toast.error(t("g.error"));
    }
  };
  return (
    <div className="flex items-center justify-between gap-2 border-b border-border/60 py-1.5 text-sm last:border-0">
      <span className="text-muted">{label}</span>
      {value ? (
        <button type="button" onClick={copy} className="max-w-[60%] truncate font-mono text-xs hover:text-accent" title={t("g.copy")}>
          {value}
        </button>
      ) : (
        <span>—</span>
      )}
    </div>
  );
}

/** One AI call in full: outcome, tokens, cost maths, the attempt timeline, identifiers and (if stored) the redacted bodies. */
export function TraceDrawer({ id, onClose, onOpen }: { id: string | null; onClose: () => void; onOpen?: (id: string) => void }) {
  const t = useTranslations("ai");
  const task = useEnum("task");
  const q = useAi<Trace>(id ? `/logs/${id}` : null);
  const l = q.data;
  return (
    <Dialog open={!!id} onClose={onClose} drawer size="xl" title={l ? `${task(l.task)} · ${l.request_id}` : t("g.loading")} footer={<Button variant="outline" onClick={onClose}>{t("g.close")}</Button>}>
      <QueryState isLoading={q.isLoading} error={q.error} onRetry={() => q.refetch()}>
        {l && (
          <div className="space-y-6">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={statusTone[l.status as keyof typeof statusTone] ?? "neutral"}>{t(`lg.s.${l.status}` as never)}</Badge>
              <span className="text-sm">{t(`tr.final.${l.final_outcome}`)}</span>
              {l.used_fallback && <Badge tone="warning">{t("tr.usedFallback")}</Badge>}
              <span className="ml-auto text-xs text-muted">{formatDateTime(l.created_at)}</span>
            </div>

            <section aria-label={t("tr.summary")} className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              <Tile label={t("lg.model")} value={<span className="text-base">{l.model ?? "—"}</span>} hint={l.provider ?? undefined} />
              <Tile label={t("g.latency")} value={`${l.latency_ms} ms`} hint={l.tokens_per_second ? t("tr.tps", { n: l.tokens_per_second }) : undefined} />
              <Tile label={t("g.cost")} value={formatMoney(l.cost)} />
              <Tile label={t("us.tokensIn")} value={l.tokens_in.toLocaleString()} />
              <Tile label={t("us.tokensOut")} value={l.tokens_out.toLocaleString()} />
              <Tile label={t("tr.tokensTotal")} value={l.tokens_total.toLocaleString()} />
            </section>

            <section aria-label={t("tr.timeline")}>
              <h3 className="mb-2 text-sm font-medium">{t("tr.timeline")}</h3>
              <Waterfall attempts={l.attempts} total={l.latency_ms} />
            </section>

            <section aria-label={t("tr.costBreakdown")}>
              <h3 className="mb-2 text-sm font-medium">{t("tr.costBreakdown")}</h3>
              <div className="overflow-x-auto rounded-lg border border-border">
                <table className="w-full text-left text-sm">
                  <thead className="bg-background text-xs uppercase tracking-wide text-muted">
                    <tr>
                      <th className="px-3 py-2 font-medium">{t("tr.part")}</th>
                      <th className="px-3 py-2 font-medium">{t("tr.tokens")}</th>
                      <th className="px-3 py-2 font-medium">{t("tr.price")}</th>
                      <th className="px-3 py-2 font-medium">{t("g.cost")}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    <tr>
                      <td className="px-3 py-2">{t("us.tokensIn")}</td>
                      <td className="px-3 py-2">{l.tokens_in.toLocaleString()}</td>
                      <td className="px-3 py-2">${l.pricing.input_price}</td>
                      <td className="px-3 py-2">{formatMoney(l.pricing.input_cost)}</td>
                    </tr>
                    <tr>
                      <td className="px-3 py-2">{t("us.tokensOut")}</td>
                      <td className="px-3 py-2">{l.tokens_out.toLocaleString()}</td>
                      <td className="px-3 py-2">${l.pricing.output_price}</td>
                      <td className="px-3 py-2">{formatMoney(l.pricing.output_cost)}</td>
                    </tr>
                    <tr className="font-medium">
                      <td className="px-3 py-2">{t("tr.total")}</td>
                      <td className="px-3 py-2">{l.tokens_total.toLocaleString()}</td>
                      <td className="px-3 py-2" />
                      <td className="px-3 py-2">{formatMoney(l.pricing.total_cost)}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <p className="mt-1 text-xs text-muted">{t("tr.priceNote", { unit: l.pricing.unit })}</p>
            </section>

            <section aria-label={t("tr.identifiers")}>
              <h3 className="mb-1 text-sm font-medium">{t("tr.identifiers")}</h3>
              <div className="rounded-lg border border-border px-3">
                <Id label={t("lg.requestId")} value={l.request_id} />
                <Id label={t("lg.trace")} value={l.trace_id} />
                <Id label={t("tr.logId")} value={l.id} />
                <Id label={t("tr.key")} value={l.key.label ? `${l.key.label} ····${l.key.last4}` : null} />
                <Id label={t("lg.error")} value={l.error_code} />
                <Id label={t("lg.depth")} value={String(l.fallback_depth)} />
              </div>
              <p className="mt-1 text-xs text-muted">{t("lg.traceNote")}</p>
            </section>

            {l.same_trace.length > 0 && (
              <section aria-label={t("tr.sameTrace")}>
                <h3 className="mb-2 text-sm font-medium">{t("tr.sameTrace")}</h3>
                <ul className="space-y-1.5">
                  {l.same_trace.map((x) => (
                    <li key={x.id} className="flex items-center justify-between gap-2 rounded-md border border-border px-3 py-1.5 text-sm">
                      <span>
                        {task(x.task)} · {x.model ?? "—"}
                      </span>
                      <span className="flex items-center gap-2">
                        <span className="text-xs text-muted">{formatMoney(x.cost)}</span>
                        {onOpen && (
                          <Button size="sm" variant="ghost" onClick={() => onOpen(x.id)}>
                            {t("ev.detail")}
                          </Button>
                        )}
                      </span>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            <section aria-label={t("tr.content")} className="space-y-3">
              <h3 className="text-sm font-medium">{t("tr.content")}</h3>
              {l.bodies_stored ? (
                <>
                  {l.prompt_redacted && <Code label={t("lg.prompt")} text={l.prompt_redacted} />}
                  {l.response_redacted && <Code label={t("lg.response")} text={l.response_redacted} />}
                </>
              ) : (
                <p className="rounded-md border border-dashed border-border px-3 py-3 text-sm text-muted">{t("lg.noBodies")}</p>
              )}
            </section>
          </div>
        )}
      </QueryState>
    </Dialog>
  );
}
