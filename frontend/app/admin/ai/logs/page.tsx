"use client";

import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import * as React from "react";
import { DataTableLite, QueryState, SectionHeader, useEnum } from "@/components/ai/common";
import { statusTone, TraceDrawer } from "@/components/ai/trace";
import { Button } from "@/components/ui/button";
import { Badge, Card } from "@/components/ui/card";
import { Checkbox, Field, Select } from "@/components/ui/fields";
import { Input } from "@/components/ui/input";
import { AI_TASKS, formatMoney } from "@/lib/ai";
import { qs, useAi } from "@/lib/ai-api";
import type { LogPage, Monitoring } from "@/lib/ai-monitor-types";
import { formatDateTime } from "@/lib/format";

function useDebounced<T>(value: T, ms = 350): T {
  const [v, setV] = React.useState(value);
  React.useEffect(() => {
    const id = setTimeout(() => setV(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return v;
}

/** 1 2 … 5 6 7 … 20: the pages around the current one, plus first and last. */
function pageWindow(page: number, pages: number): (number | "gap")[] {
  const set = new Set([1, pages, page - 1, page, page + 1].filter((p) => p >= 1 && p <= pages));
  const sorted = [...set].sort((a, b) => a - b);
  const out: (number | "gap")[] = [];
  sorted.forEach((p, i) => {
    if (i > 0 && p - sorted[i - 1] > 1) out.push("gap");
    out.push(p);
  });
  return out;
}

function LogsInner() {
  const t = useTranslations("ai");
  const task = useEnum("task");
  const params = useSearchParams();
  const init = (k: string) => params.get(k) ?? "";
  const [requestId, setRequestId] = React.useState(init("request_id"));
  const [taskF, setTaskF] = React.useState(init("task"));
  const [status, setStatus] = React.useState(init("status"));
  const [provider, setProvider] = React.useState(init("provider"));
  const [model, setModel] = React.useState(init("model"));
  const [range, setRange] = React.useState(init("range") || (init("from") ? "custom" : "7d"));
  const [from, setFrom] = React.useState(init("from"));
  const [to, setTo] = React.useState(init("to"));
  const [minLatency, setMinLatency] = React.useState("");
  const [minCost, setMinCost] = React.useState("");
  const [fallbackOnly, setFallbackOnly] = React.useState(false);
  const [sort, setSort] = React.useState("created_at");
  const [dir, setDir] = React.useState("desc");
  const [size, setSize] = React.useState(25);
  const [page, setPage] = React.useState(1);
  const [open, setOpen] = React.useState<string | null>(null);
  const rid = useDebounced(requestId);
  const ml = useDebounced(minLatency);
  const mc = useDebounced(minCost);

  React.useEffect(() => setPage(1), [rid, taskF, status, provider, model, range, from, to, ml, mc, fallbackOnly, sort, dir, size]);

  const facets = useAi<Monitoring>("/monitoring?range=1m");
  const custom = range === "custom";
  const logs = useAi<LogPage>(
    `/logs${qs({
      request_id: rid, task: taskF, status, provider, model, fallback_only: fallbackOnly || undefined, min_latency_ms: ml, min_cost: mc,
      range: custom ? undefined : range === "all" ? undefined : range, date_from: custom && from ? `${from}T00:00:00+05:30` : undefined,
      date_to: custom && to ? `${to}T23:59:59+05:30` : undefined, sort, direction: dir, limit: size, offset: (page - 1) * size,
    })}`,
  );
  const total = logs.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / size));

  const clear = () => {
    setRequestId(""); setTaskF(""); setStatus(""); setProvider(""); setModel(""); setRange("7d"); setFrom(""); setTo("");
    setMinLatency(""); setMinCost(""); setFallbackOnly(false); setSort("created_at"); setDir("desc");
  };

  return (
    <>
      <SectionHeader title={t("lg.title")} description={t("lg.description")} />
      <Card className="mb-5 space-y-4">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Field label={t("lg.requestId")} htmlFor="lg-rid">
            <Input id="lg-rid" type="search" placeholder={t("lg.search")} value={requestId} onChange={(e) => setRequestId(e.target.value)} />
          </Field>
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
          <Field label={t("lg.provider")} htmlFor="lg-prov">
            <Select id="lg-prov" value={provider} onChange={(e) => setProvider(e.target.value)}>
              <option value="">{t("g.all")}</option>
              {(facets.data?.facets.providers ?? []).map((x) => <option key={x} value={x}>{x}</option>)}
            </Select>
          </Field>
          <Field label={t("lg.model")} htmlFor="lg-model">
            <Select id="lg-model" value={model} onChange={(e) => setModel(e.target.value)}>
              <option value="">{t("g.all")}</option>
              {(facets.data?.facets.models ?? []).map((x) => <option key={x} value={x}>{x}</option>)}
            </Select>
          </Field>
          <Field label={t("lg.period")} htmlFor="lg-range">
            <Select id="lg-range" value={range} onChange={(e) => setRange(e.target.value)}>
              {(["1d", "3d", "7d", "3w", "1m"] as const).map((r) => <option key={r} value={r}>{t(`mon.range.${r}`)}</option>)}
              <option value="all">{t("lg.allTime")}</option>
              <option value="custom">{t("mon.range.custom")}</option>
            </Select>
          </Field>
          {custom && (
            <>
              <Field label={t("g.fromDate")} htmlFor="lg-from"><Input id="lg-from" type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
              <Field label={t("g.toDate")} htmlFor="lg-to"><Input id="lg-to" type="date" value={to} onChange={(e) => setTo(e.target.value)} /></Field>
            </>
          )}
          <Field label={t("lg.minLatency")} htmlFor="lg-ml"><Input id="lg-ml" type="number" min={0} placeholder="0" value={minLatency} onChange={(e) => setMinLatency(e.target.value)} /></Field>
          <Field label={t("lg.minCost")} htmlFor="lg-mc"><Input id="lg-mc" type="number" min={0} step="0.0001" placeholder="0.0000" value={minCost} onChange={(e) => setMinCost(e.target.value)} /></Field>
          <Field label={t("lg.sortBy")} htmlFor="lg-sort">
            <Select id="lg-sort" value={sort} onChange={(e) => setSort(e.target.value)}>
              {(["created_at", "cost", "latency", "tokens"] as const).map((s) => <option key={s} value={s}>{t(`lg.sort.${s}`)}</option>)}
            </Select>
          </Field>
          <Field label={t("lg.direction")} htmlFor="lg-dir">
            <Select id="lg-dir" value={dir} onChange={(e) => setDir(e.target.value)}>
              <option value="desc">{t("lg.desc")}</option>
              <option value="asc">{t("lg.asc")}</option>
            </Select>
          </Field>
          <Field label={t("lg.pageSize")} htmlFor="lg-size">
            <Select id="lg-size" value={size} onChange={(e) => setSize(Number(e.target.value))}>
              {[10, 25, 50, 100].map((n) => <option key={n} value={n}>{n}</option>)}
            </Select>
          </Field>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Checkbox label={t("lg.fallbackOnly")} checked={fallbackOnly} onChange={(e) => setFallbackOnly(e.target.checked)} />
          <Button size="sm" variant="outline" onClick={clear}>{t("lg.clear")}</Button>
        </div>
      </Card>

      {logs.data && (
        <p className="mb-3 text-sm text-muted" aria-live="polite">
          {t("lg.summary", { n: total.toLocaleString(), cost: formatMoney(logs.data.page_cost), tin: logs.data.page_tokens_in.toLocaleString(), tout: logs.data.page_tokens_out.toLocaleString() })}
        </p>
      )}

      <QueryState isLoading={logs.isLoading} error={logs.error} empty={!!logs.data && logs.data.items.length === 0} onRetry={() => logs.refetch()}>
        <DataTableLite caption={t("lg.title")} head={[t("lg.when"), t("lg.task"), t("lg.model"), t("lg.status"), t("us.tokensIn"), t("us.tokensOut"), t("g.cost"), t("g.latency"), t("lg.depth"), t("lg.requestId")]}>
          {logs.data?.items.map((l) => (
            <tr key={l.id} className="cursor-pointer align-top hover:bg-accent-soft/50" onClick={() => setOpen(l.id)}>
              <td className="whitespace-nowrap px-4 py-2 text-muted">{formatDateTime(l.created_at)}</td>
              <td className="px-4 py-2">{task(l.task)}</td>
              <td className="px-4 py-2">
                <button type="button" className="text-left font-medium hover:text-accent" onClick={(e) => { e.stopPropagation(); setOpen(l.id); }}>{l.model ?? "—"}</button>
                <div className="text-xs text-muted">{l.provider ?? ""}</div>
              </td>
              <td className="px-4 py-2"><Badge tone={statusTone[l.status as keyof typeof statusTone] ?? "neutral"}>{t(`lg.s.${l.status}` as never)}</Badge>{l.error_code && <div className="mt-0.5 font-mono text-[11px] text-muted">{l.error_code}</div>}</td>
              <td className="px-4 py-2 tabular-nums">{l.tokens_in.toLocaleString()}</td>
              <td className="px-4 py-2 tabular-nums">{l.tokens_out.toLocaleString()}</td>
              <td className="px-4 py-2 tabular-nums">{formatMoney(l.cost)}</td>
              <td className="px-4 py-2 tabular-nums">{l.latency_ms} ms</td>
              <td className="px-4 py-2">{l.fallback_depth > 0 ? <Badge tone="warning">+{l.fallback_depth}</Badge> : "—"}</td>
              <td className="px-4 py-2 font-mono text-xs text-muted">{l.request_id.slice(0, 14)}</td>
            </tr>
          ))}
        </DataTableLite>
        <nav aria-label={t("lg.pagination")} className="mt-3 flex flex-wrap items-center justify-between gap-3 text-sm">
          <span aria-live="polite">{t("lg.of", { from: total ? (page - 1) * size + 1 : 0, to: Math.min(total, page * size), total: total.toLocaleString() })}</span>
          <div className="flex flex-wrap items-center gap-1.5">
            <Button size="sm" variant="outline" disabled={page === 1} onClick={() => setPage(1)}>{t("lg.first")}</Button>
            <Button size="sm" variant="outline" disabled={page === 1} onClick={() => setPage(page - 1)}>{t("lg.prev")}</Button>
            {pageWindow(page, pages).map((p, i) =>
              p === "gap" ? (
                <span key={`g${i}`} className="px-1 text-muted">…</span>
              ) : (
                <Button key={p} size="sm" variant={p === page ? "primary" : "outline"} aria-current={p === page ? "page" : undefined} onClick={() => setPage(p)}>{p}</Button>
              ),
            )}
            <Button size="sm" variant="outline" disabled={page >= pages} onClick={() => setPage(page + 1)}>{t("lg.next")}</Button>
            <Button size="sm" variant="outline" disabled={page >= pages} onClick={() => setPage(pages)}>{t("lg.last")}</Button>
          </div>
        </nav>
      </QueryState>
      <TraceDrawer id={open} onClose={() => setOpen(null)} onOpen={setOpen} />
    </>
  );
}

export default function LogsPage() {
  return (
    <React.Suspense fallback={null}>
      <LogsInner />
    </React.Suspense>
  );
}
