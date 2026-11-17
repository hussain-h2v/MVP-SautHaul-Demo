"use client";

import { Copy } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";
import { toast } from "sonner";
import { DataTableLite, PathChain, QueryState, SectionHeader, useEnum } from "@/components/ai/common";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, Select } from "@/components/ui/fields";
import { Input } from "@/components/ui/input";
import { AI_TASKS, formatMoney } from "@/lib/ai";
import { qs, useAi } from "@/lib/ai-api";
import type { AiLog } from "@/lib/ai-types";
import { formatDateTime } from "@/lib/format";

const PAGE = 25;
const statusTone = { ok: "success", failed: "danger", disabled: "neutral" } as const;

function useDebounced<T>(value: T, ms = 350): T {
  const [v, setV] = React.useState(value);
  React.useEffect(() => {
    const id = setTimeout(() => setV(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return v;
}

function LogDrawer({ id, onClose }: { id: string | null; onClose: () => void }) {
  const t = useTranslations("ai");
  const log = useAi<AiLog>(id ? `/logs/${id}` : null);
  const l = log.data;
  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      toast.success(t("g.copied"));
    } catch {
      toast.error(t("g.error"));
    }
  };
  return (
    <Dialog open={!!id} onClose={onClose} drawer title={l ? `${l.task} · ${l.request_id}` : t("g.loading")} footer={<Button variant="outline" onClick={onClose}>{t("g.close")}</Button>}>
      <QueryState isLoading={log.isLoading} error={log.error}>
        {l && (
          <div className="space-y-5">
            <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
              <dt className="text-muted">{t("lg.provider")}</dt><dd>{l.provider ?? "—"}</dd>
              <dt className="text-muted">{t("lg.model")}</dt><dd>{l.model ?? "—"}</dd>
              <dt className="text-muted">{t("lg.status")}</dt><dd><Badge tone={statusTone[l.status as keyof typeof statusTone] ?? "neutral"}>{l.status}</Badge></dd>
              <dt className="text-muted">{t("lg.depth")}</dt><dd>{l.fallback_depth}</dd>
              <dt className="text-muted">{t("us.tokensIn")} / {t("us.tokensOut")}</dt><dd>{l.tokens_in} / {l.tokens_out}</dd>
              <dt className="text-muted">{t("g.cost")}</dt><dd>{formatMoney(l.cost)}</dd>
              <dt className="text-muted">{t("g.latency")}</dt><dd>{l.latency_ms} ms</dd>
              <dt className="text-muted">{t("lg.error")}</dt><dd>{l.error_code ?? "—"}</dd>
              <dt className="text-muted">{t("lg.when")}</dt><dd>{formatDateTime(l.created_at)}</dd>
            </dl>
            <div>
              <h3 className="mb-2 text-sm font-medium">{t("lg.path")}</h3>
              <PathChain path={l.path} />
            </div>
            <div>
              <h3 className="mb-1 text-sm font-medium">{t("lg.trace")}</h3>
              {l.trace_id ? (
                <div className="flex items-center gap-2">
                  <code className="break-all rounded bg-background px-2 py-1 text-xs">{l.trace_id}</code>
                  <Button size="sm" variant="outline" onClick={() => copy(l.trace_id!)} aria-label={`${t("g.copy")} ${t("lg.trace")}`}>
                    <Copy className="size-3.5" aria-hidden="true" />
                    {t("g.copy")}
                  </Button>
                </div>
              ) : (
                <p className="text-sm text-muted">—</p>
              )}
              <p className="mt-1 text-xs text-muted">{t("lg.traceNote")}</p>
            </div>
            {l.prompt_redacted || l.response_redacted ? (
              <>
                <div>
                  <h3 className="mb-1 text-sm font-medium">{t("lg.prompt")}</h3>
                  <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-md border border-border bg-background p-3 text-xs">{l.prompt_redacted}</pre>
                </div>
                <div>
                  <h3 className="mb-1 text-sm font-medium">{t("lg.response")}</h3>
                  <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-md border border-border bg-background p-3 text-xs">{l.response_redacted}</pre>
                </div>
              </>
            ) : (
              <p className="text-sm text-muted">{t("lg.noBodies")}</p>
            )}
          </div>
        )}
      </QueryState>
    </Dialog>
  );
}

export default function LogsPage() {
  const t = useTranslations("ai");
  const task = useEnum("task");
  const [requestId, setRequestId] = React.useState("");
  const [taskF, setTaskF] = React.useState("");
  const [status, setStatus] = React.useState("");
  const [provider, setProvider] = React.useState("");
  const [from, setFrom] = React.useState("");
  const [to, setTo] = React.useState("");
  const [offset, setOffset] = React.useState(0);
  const [open, setOpen] = React.useState<string | null>(null);
  const rid = useDebounced(requestId);
  const prov = useDebounced(provider);
  React.useEffect(() => setOffset(0), [rid, taskF, status, prov, from, to]);
  const logs = useAi<{ total: number; items: AiLog[] }>(
    `/logs${qs({ request_id: rid, task: taskF, status, provider: prov, date_from: from, date_to: to, limit: PAGE, offset })}`,
  );
  const total = logs.data?.total ?? 0;

  return (
    <>
      <SectionHeader title={t("lg.title")} description={t("lg.description")} />
      <div className="mb-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Field label={t("lg.requestId")} htmlFor="lg-rid"><Input id="lg-rid" type="search" placeholder={t("lg.search")} value={requestId} onChange={(e) => setRequestId(e.target.value)} /></Field>
        <Field label={t("lg.task")} htmlFor="lg-task">
          <Select id="lg-task" value={taskF} onChange={(e) => setTaskF(e.target.value)}>
            <option value="">{t("g.all")}</option>
            {AI_TASKS.map((x) => <option key={x} value={x}>{task(x)}</option>)}
          </Select>
        </Field>
        <Field label={t("lg.status")} htmlFor="lg-status">
          <Select id="lg-status" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">{t("g.all")}</option>
            {(["ok", "failed", "disabled"] as const).map((s) => <option key={s} value={s}>{t(`lg.s.${s}`)}</option>)}
          </Select>
        </Field>
        <Field label={t("lg.provider")} htmlFor="lg-prov"><Input id="lg-prov" value={provider} onChange={(e) => setProvider(e.target.value)} /></Field>
        <Field label={t("g.fromDate")} htmlFor="lg-from"><Input id="lg-from" type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
        <Field label={t("g.toDate")} htmlFor="lg-to"><Input id="lg-to" type="date" value={to} onChange={(e) => setTo(e.target.value)} /></Field>
      </div>
      <QueryState isLoading={logs.isLoading} error={logs.error} empty={!!logs.data && logs.data.items.length === 0} onRetry={() => logs.refetch()}>
        <DataTableLite caption={t("lg.title")} head={[t("lg.when"), t("lg.task"), t("lg.provider"), t("lg.model"), t("lg.status"), t("lg.depth"), t("g.latency"), t("g.cost"), t("lg.error"), ""]}>
          {logs.data?.items.map((l) => (
            <tr key={l.id} className="align-top">
              <td className="whitespace-nowrap px-4 py-2 text-muted">{formatDateTime(l.created_at)}</td>
              <td className="px-4 py-2">{task(l.task)}</td>
              <td className="px-4 py-2">{l.provider ?? "—"}</td>
              <td className="px-4 py-2">{l.model ?? "—"}</td>
              <td className="px-4 py-2"><Badge tone={statusTone[l.status as keyof typeof statusTone] ?? "neutral"}>{l.status}</Badge></td>
              <td className="px-4 py-2">{l.fallback_depth}</td>
              <td className="px-4 py-2">{l.latency_ms} ms</td>
              <td className="px-4 py-2">{formatMoney(l.cost)}</td>
              <td className="px-4 py-2 font-mono text-xs">{l.error_code ?? "—"}</td>
              <td className="px-4 py-2"><Button size="sm" variant="ghost" onClick={() => setOpen(l.id)}>{t("ev.detail")}</Button></td>
            </tr>
          ))}
        </DataTableLite>
        <div className="mt-3 flex items-center justify-between text-sm">
          <span aria-live="polite">{t("lg.of", { from: total ? offset + 1 : 0, to: Math.min(total, offset + PAGE), total })}</span>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>{t("lg.prev")}</Button>
            <Button size="sm" variant="outline" disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)}>{t("lg.next")}</Button>
          </div>
        </div>
      </QueryState>
      <LogDrawer id={open} onClose={() => setOpen(null)} />
    </>
  );
}
