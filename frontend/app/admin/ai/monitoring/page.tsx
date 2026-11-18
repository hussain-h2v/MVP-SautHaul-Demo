"use client";

import { ArrowDownRight, ArrowUpRight, ListFilter, Minus, RefreshCw } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import * as React from "react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { DataTableLite, QueryState, SectionHeader, useEnum } from "@/components/ai/common";
import { statusTone, TraceDrawer } from "@/components/ai/trace";
import { Button } from "@/components/ui/button";
import { Badge, Card } from "@/components/ui/card";
import { Field, Select } from "@/components/ui/fields";
import { Input } from "@/components/ui/input";
import { formatMoney, formatRate, PALETTE } from "@/lib/ai";
import { qs, useAi } from "@/lib/ai-api";
import type { Agg, CallRow, Monitoring, RangeKey } from "@/lib/ai-monitor-types";
import { formatDateTime } from "@/lib/format";

const RANGES: RangeKey[] = ["1d", "3d", "7d", "3w", "1m", "custom"];

function Delta({ v, inverse = true }: { v: number | null; inverse?: boolean }) {
  const t = useTranslations("ai");
  if (v === null) return <span className="text-xs text-muted">{t("mon.noPrev")}</span>;
  if (v === 0) return <span className="inline-flex items-center gap-0.5 text-xs text-muted"><Minus className="size-3" aria-hidden="true" />0%</span>;
  const up = v > 0;
  const bad = inverse ? up : !up;
  const Icon = up ? ArrowUpRight : ArrowDownRight;
  return (
    <span className={`inline-flex items-center gap-0.5 text-xs font-medium ${bad ? "text-danger" : "text-success"}`}>
      <Icon className="size-3.5" aria-hidden="true" />
      {Math.abs(v)}% <span className="font-normal text-muted">{t("mon.vsPrev")}</span>
    </span>
  );
}

function Kpi({ label, value, sub, hint }: { label: string; value: string; sub?: React.ReactNode; hint?: string }) {
  return (
    <Card className="!p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
      <div className="mt-0.5 min-h-4">{sub ?? (hint && <span className="text-xs text-muted">{hint}</span>)}</div>
    </Card>
  );
}

function ChartCard({ title, children, note }: { title: string; children: React.ReactElement; note?: string }) {
  return (
    <Card>
      <h3 className="text-sm font-medium">{title}</h3>
      {note && <p className="mb-2 text-xs text-muted">{note}</p>}
      <div className="mt-2 h-60 w-full" role="img" aria-label={title}>
        <ResponsiveContainer width="100%" height="100%">
          {children}
        </ResponsiveContainer>
      </div>
    </Card>
  );
}

function ShareBar({ share }: { share: number }) {
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-24 rounded-full bg-background" aria-hidden="true">
        <div className="h-2 rounded-full" style={{ width: `${Math.max(2, share * 100)}%`, background: PALETTE[0] }} />
      </div>
      <span className="text-xs tabular-nums text-muted">{(share * 100).toFixed(1)}%</span>
    </div>
  );
}

function Breakdown({ title, rows, label, onOpenLogs }: { title: string; rows: (Agg & { key: string; cost_share: number })[]; label: (k: string) => string; onOpenLogs: (k: string) => string }) {
  const t = useTranslations("ai");
  return (
    <section aria-label={title}>
      <h3 className="mb-2 text-sm font-medium">{title}</h3>
      <DataTableLite caption={title} head={[t("mon.name"), t("g.requests"), t("us.tokensIn"), t("us.tokensOut"), t("g.cost"), t("mon.share"), t("mon.avgLatency"), "p95", t("us.errorRate"), ""]}>
        {rows.map((r) => (
          <tr key={r.key}>
            <td className="px-4 py-2 font-medium">{label(r.key)}</td>
            <td className="px-4 py-2 tabular-nums">{r.requests.toLocaleString()}</td>
            <td className="px-4 py-2 tabular-nums">{r.tokens_in.toLocaleString()}</td>
            <td className="px-4 py-2 tabular-nums">{r.tokens_out.toLocaleString()}</td>
            <td className="px-4 py-2 tabular-nums">{formatMoney(r.cost)}</td>
            <td className="px-4 py-2"><ShareBar share={r.cost_share} /></td>
            <td className="px-4 py-2 tabular-nums">{r.avg_ms} ms</td>
            <td className="px-4 py-2 tabular-nums">{r.p95_ms} ms</td>
            <td className="px-4 py-2 tabular-nums">{formatRate(r.error_rate)}</td>
            <td className="px-4 py-2"><Link className="text-xs text-accent hover:underline" href={onOpenLogs(r.key)}>{t("mon.viewLogs")}</Link></td>
          </tr>
        ))}
      </DataTableLite>
    </section>
  );
}

function CallList({ title, rows, onOpen, metric }: { title: string; rows: CallRow[]; onOpen: (id: string) => void; metric: "cost" | "latency" }) {
  const t = useTranslations("ai");
  const task = useEnum("task");
  return (
    <Card>
      <h3 className="mb-2 text-sm font-medium">{title}</h3>
      {rows.length === 0 ? <p className="text-sm text-muted">{t("g.empty")}</p> : (
        <ul className="divide-y divide-border">
          {rows.map((r) => (
            <li key={r.id}>
              <button type="button" onClick={() => onOpen(r.id)} className="flex w-full items-center justify-between gap-3 py-2 text-left text-sm hover:text-accent">
                <span>
                  <span className="font-medium">{task(r.task)}</span> · <span className="text-muted">{r.model ?? "—"}</span>
                  <span className="block text-xs text-muted">{formatDateTime(r.created_at)} · {r.tokens_in + r.tokens_out} {t("g.tokens").toLowerCase()}</span>
                </span>
                <span className="flex items-center gap-2">
                  <Badge tone={statusTone[r.status as keyof typeof statusTone] ?? "neutral"}>{t(`lg.s.${r.status}` as never)}</Badge>
                  <span className="font-semibold tabular-nums">{metric === "cost" ? formatMoney(r.cost) : `${r.latency_ms} ms`}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export default function MonitoringPage() {
  const t = useTranslations("ai");
  const task = useEnum("task");
  const [range, setRange] = React.useState<RangeKey>("7d");
  const [from, setFrom] = React.useState("");
  const [to, setTo] = React.useState("");
  const [taskF, setTaskF] = React.useState("");
  const [provider, setProvider] = React.useState("");
  const [model, setModel] = React.useState("");
  const [status, setStatus] = React.useState("");
  const [open, setOpen] = React.useState<string | null>(null);
  const custom = range === "custom";
  const ready = !custom || !!from;
  const q = useAi<Monitoring>(
    ready
      ? `/monitoring${qs({
          range, task: taskF, provider, model, status,
          date_from: custom && from ? `${from}T00:00:00+05:30` : undefined, date_to: custom && to ? `${to}T23:59:59+05:30` : undefined,
        })}`
      : null,
    { refetchInterval: 30000 },
  );
  const d = q.data;
  const k = d?.kpis;
  const hourly = d?.period.bucket === "hour";
  const series = (d?.series ?? []).map((s) => ({ ...s, label: hourly ? s.bucket.slice(5, 16).replace(" ", " ") : s.bucket.slice(5), costN: Number(s.cost), err_pct: Math.round(s.error_rate * 1000) / 10 }));
  const logsHref = (extra: Record<string, string>) => `/admin/ai/logs${qs({ range: custom ? "7d" : range, task: taskF, provider, model, status, ...extra })}`;

  return (
    <>
      <SectionHeader
        title={t("mon.title")}
        description={t("mon.description")}
        actions={<Button size="sm" variant="outline" onClick={() => q.refetch()}><RefreshCw className={`size-3.5 ${q.isFetching ? "animate-spin" : ""}`} aria-hidden="true" />{t("mon.refresh")}</Button>}
      />

      <Card className="mb-6 space-y-4">
        <div role="group" aria-label={t("mon.rangeLabel")} className="flex flex-wrap gap-2">
          {RANGES.map((r) => (
            <Button key={r} size="sm" variant={range === r ? "primary" : "outline"} aria-pressed={range === r} onClick={() => setRange(r)}>{t(`mon.range.${r}`)}</Button>
          ))}
        </div>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {custom && (
            <>
              <Field label={t("g.fromDate")} htmlFor="mo-from"><Input id="mo-from" type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
              <Field label={t("g.toDate")} htmlFor="mo-to"><Input id="mo-to" type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} /></Field>
            </>
          )}
          <Field label={t("lg.task")} htmlFor="mo-task">
            <Select id="mo-task" value={taskF} onChange={(e) => setTaskF(e.target.value)}>
              <option value="">{t("g.all")}</option>
              {(d?.facets.tasks ?? []).map((x) => <option key={x} value={x}>{task(x)}</option>)}
            </Select>
          </Field>
          <Field label={t("lg.provider")} htmlFor="mo-prov">
            <Select id="mo-prov" value={provider} onChange={(e) => setProvider(e.target.value)}>
              <option value="">{t("g.all")}</option>
              {(d?.facets.providers ?? []).map((x) => <option key={x} value={x}>{x}</option>)}
            </Select>
          </Field>
          <Field label={t("lg.model")} htmlFor="mo-model">
            <Select id="mo-model" value={model} onChange={(e) => setModel(e.target.value)}>
              <option value="">{t("g.all")}</option>
              {(d?.facets.models ?? []).map((x) => <option key={x} value={x}>{x}</option>)}
            </Select>
          </Field>
          <Field label={t("lg.status")} htmlFor="mo-status">
            <Select id="mo-status" value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">{t("g.all")}</option>
              {(["ok", "failed", "disabled"] as const).map((s) => <option key={s} value={s}>{t(`lg.s.${s}`)}</option>)}
            </Select>
          </Field>
        </div>
        {d && <p className="text-xs text-muted">{t("mon.periodNote", { from: formatDateTime(d.period.from), to: formatDateTime(d.period.to), tz: d.period.timezone, bucket: t(`mon.bucket.${d.period.bucket}`) })}</p>}
      </Card>

      {!ready ? <p className="text-sm text-muted">{t("mon.pickDates")}</p> : (
        <QueryState isLoading={q.isLoading} error={q.error} onRetry={() => q.refetch()}>
          {d && k && (
            <div className="space-y-8">
              <section aria-label={t("mon.spend")}>
                <h3 className="mb-2 text-sm font-medium">{t("mon.spend")}</h3>
                <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                  <Kpi label={t("mon.today")} value={formatMoney(d.spend.today.cost)} hint={t("mon.calls", { n: d.spend.today.requests.toLocaleString() })} />
                  <Kpi label={t("mon.last7")} value={formatMoney(d.spend.last_7d.cost)} hint={t("mon.calls", { n: d.spend.last_7d.requests.toLocaleString() })} />
                  <Kpi label={t("mon.mtd", { month: d.spend.month })} value={formatMoney(d.spend.month_to_date.cost)} hint={t("mon.calls", { n: d.spend.month_to_date.requests.toLocaleString() })} />
                  <Kpi label={t("mon.projected")} value={formatMoney(d.spend.projected_month)} hint={t("mon.projectedHint")} />
                </div>
              </section>

              <section aria-label={t("mon.periodKpis")}>
                <h3 className="mb-2 text-sm font-medium">{t("mon.periodKpis")}</h3>
                <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
                  <Kpi label={t("g.requests")} value={k.requests.toLocaleString()} sub={<Delta v={d.change.requests} inverse={false} />} />
                  <Kpi label={t("mon.periodCost")} value={formatMoney(k.cost)} sub={<Delta v={d.change.cost} />} />
                  <Kpi label={t("mon.avgCost")} value={formatMoney(k.avg_cost)} hint={t("mon.perCall")} />
                  <Kpi label={t("us.tokensIn")} value={k.tokens_in.toLocaleString()} />
                  <Kpi label={t("us.tokensOut")} value={k.tokens_out.toLocaleString()} />
                  <Kpi label={t("mon.avgLatency")} value={`${k.avg_ms} ms`} sub={<Delta v={d.change.avg_ms} />} />
                  <Kpi label={t("us.p50")} value={`${k.p50_ms} ms`} />
                  <Kpi label={t("us.p95")} value={`${k.p95_ms} ms`} />
                  <Kpi label={t("mon.p99")} value={`${k.p99_ms} ms`} hint={t("mon.slowest", { ms: k.max_ms })} />
                  <Kpi label={t("us.errorRate")} value={formatRate(k.error_rate)} sub={<Delta v={d.change.error_rate} />} hint={t("mon.failedOf", { f: k.failed, n: k.requests })} />
                </div>
                <p className="mt-2 text-xs text-muted">{t("us.fallbackRate")}: {formatRate(k.fallback_rate)}</p>
              </section>

              {k.requests === 0 ? (
                <p className="rounded-md border border-dashed border-border px-4 py-8 text-center text-sm text-muted">{t("mon.noData")}</p>
              ) : (
                <>
                  <div className="grid gap-4 lg:grid-cols-2">
                    <ChartCard title={t("mon.chartCost", { bucket: t(`mon.bucket.${d.period.bucket}`) })}>
                      <BarChart data={series}>
                        <CartesianGrid strokeDasharray="3 3" />
                        <XAxis dataKey="label" minTickGap={24} fontSize={11} />
                        <YAxis tickFormatter={(v) => `$${Number(v).toFixed(2)}`} fontSize={11} width={56} />
                        <Tooltip formatter={(v) => formatMoney(Number(v))} />
                        <Bar dataKey="costN" fill={PALETTE[1]} name={t("g.cost")} />
                      </BarChart>
                    </ChartCard>
                    <ChartCard title={t("mon.chartRequests")}>
                      <BarChart data={series}>
                        <CartesianGrid strokeDasharray="3 3" />
                        <XAxis dataKey="label" minTickGap={24} fontSize={11} />
                        <YAxis allowDecimals={false} fontSize={11} width={40} />
                        <Tooltip />
                        <Legend />
                        <Bar dataKey="ok" stackId="a" fill={PALETTE[2]} name={t("lg.s.ok")} />
                        <Bar dataKey="failed" stackId="a" fill={PALETTE[4]} name={t("lg.s.failed")} />
                      </BarChart>
                    </ChartCard>
                    <ChartCard title={t("mon.chartTokens")}>
                      <AreaChart data={series}>
                        <CartesianGrid strokeDasharray="3 3" />
                        <XAxis dataKey="label" minTickGap={24} fontSize={11} />
                        <YAxis fontSize={11} width={52} />
                        <Tooltip />
                        <Legend />
                        <Area type="monotone" dataKey="tokens_in" stackId="t" stroke={PALETTE[0]} fill={PALETTE[0]} fillOpacity={0.35} name={t("us.tokensIn")} />
                        <Area type="monotone" dataKey="tokens_out" stackId="t" stroke={PALETTE[5]} fill={PALETTE[5]} fillOpacity={0.35} name={t("us.tokensOut")} />
                      </AreaChart>
                    </ChartCard>
                    <ChartCard title={t("mon.chartLatency")}>
                      <LineChart data={series}>
                        <CartesianGrid strokeDasharray="3 3" />
                        <XAxis dataKey="label" minTickGap={24} fontSize={11} />
                        <YAxis unit=" ms" fontSize={11} width={60} />
                        <Tooltip />
                        <Legend />
                        <Line type="monotone" dataKey="avg_ms" stroke={PALETTE[0]} strokeWidth={2} dot={false} name={t("mon.avgLatency")} />
                        <Line type="monotone" dataKey="p95_ms" stroke={PALETTE[4]} strokeWidth={2} strokeDasharray="6 3" dot={false} name={t("us.p95")} />
                      </LineChart>
                    </ChartCard>
                  </div>

                  <Breakdown title={t("mon.byModel")} rows={d.by_model} label={(x) => x} onOpenLogs={(x) => logsHref({ model: x })} />
                  <Breakdown title={t("mon.byProvider")} rows={d.by_provider} label={(x) => x} onOpenLogs={(x) => logsHref({ provider: x })} />
                  <Breakdown title={t("mon.byTask")} rows={d.by_task} label={task} onOpenLogs={(x) => logsHref({ task: x })} />

                  <section aria-label={t("mon.daily")}>
                    <h3 className="mb-2 text-sm font-medium">{t("mon.daily")}</h3>
                    <DataTableLite caption={t("mon.daily")} head={[t("mon.day"), t("g.requests"), t("us.tokensIn"), t("us.tokensOut"), t("g.cost"), t("mon.avgLatency"), t("us.errorRate"), ""]}>
                      {d.daily.map((r) => (
                        <tr key={r.bucket}>
                          <td className="px-4 py-2 font-medium">{r.bucket}</td>
                          <td className="px-4 py-2 tabular-nums">{r.requests.toLocaleString()}</td>
                          <td className="px-4 py-2 tabular-nums">{r.tokens_in.toLocaleString()}</td>
                          <td className="px-4 py-2 tabular-nums">{r.tokens_out.toLocaleString()}</td>
                          <td className="px-4 py-2 font-medium tabular-nums">{formatMoney(r.cost)}</td>
                          <td className="px-4 py-2 tabular-nums">{r.avg_ms} ms</td>
                          <td className="px-4 py-2 tabular-nums">{formatRate(r.error_rate)}</td>
                          <td className="px-4 py-2">
                            <Link className="text-xs text-accent hover:underline" href={`/admin/ai/logs${qs({ range: "custom", from: r.bucket, to: r.bucket, task: taskF, provider, model, status })}`}>
                              <ListFilter className="mr-1 inline size-3" aria-hidden="true" />{t("mon.viewLogs")}
                            </Link>
                          </td>
                        </tr>
                      ))}
                    </DataTableLite>
                  </section>

                  <div className="grid gap-4 lg:grid-cols-2">
                    <CallList title={t("mon.topCost")} rows={d.top_cost} onOpen={setOpen} metric="cost" />
                    <CallList title={t("mon.topSlow")} rows={d.top_slow} onOpen={setOpen} metric="latency" />
                  </div>

                  <div className="flex justify-end">
                    <Link href={logsHref({})}><Button variant="outline">{t("mon.openLogs")}</Button></Link>
                  </div>
                </>
              )}
            </div>
          )}
        </QueryState>
      )}
      <TraceDrawer id={open} onClose={() => setOpen(null)} onOpen={setOpen} />
    </>
  );
}
