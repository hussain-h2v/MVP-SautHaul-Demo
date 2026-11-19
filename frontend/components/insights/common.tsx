"use client";

import { ArrowDownRight, ArrowUpRight, Download, Minus, Sparkles } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge, Card, Skeleton } from "@/components/ui/card";
import { downloadCsv } from "@/lib/api";
import { PALETTE } from "@/lib/ai";
import { changeTone, formatKpi, heatOpacity, qs, RANGES, useNarrative, type InsightsView, type Kpi, type RangeKey, type ViewKey } from "@/lib/insights";
import { errorMessage } from "@/lib/use-api";
import { cn } from "@/lib/utils";

export function RangeChips({ value, onChange }: { value: RangeKey; onChange: (r: RangeKey) => void }) {
  const t = useTranslations("insights");
  return (
    <div role="group" aria-label={t("rangeLabel")} className="flex flex-wrap gap-2">
      {RANGES.map((r) => (
        <Button key={r} size="sm" variant={value === r ? "primary" : "outline"} aria-pressed={value === r} onClick={() => onChange(r)}>
          {t(`range.${r}`)}
        </Button>
      ))}
    </div>
  );
}

function Delta({ kpi }: { kpi: Kpi }) {
  const t = useTranslations("insights");
  if (kpi.change === null) return <span className="text-xs text-muted">{t("noPrev")}</span>;
  if (kpi.change === 0) return <span className="inline-flex items-center gap-0.5 text-xs text-muted"><Minus className="size-3" aria-hidden="true" />0%</span>;
  const tone = changeTone(kpi.change, kpi.good_when_up);
  const Icon = kpi.change > 0 ? ArrowUpRight : ArrowDownRight;
  return (
    <span className={cn("inline-flex items-center gap-0.5 text-xs font-medium", tone === "good" ? "text-success" : tone === "bad" ? "text-danger" : "text-muted")}>
      <Icon className="size-3.5" aria-hidden="true" />
      {Math.abs(kpi.change)}% <span className="font-normal text-muted">{t("vsPrev")}</span>
    </span>
  );
}

export function KpiGrid({ view, keys, labelPrefix }: { view: InsightsView; keys?: string[]; labelPrefix?: string }) {
  const t = useTranslations("insights");
  const list = keys ?? Object.keys(view.kpis);
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {list.map((k) => {
        const kpi = view.kpis[k];
        if (!kpi) return null;
        return (
          <Card key={k} className="!p-4">
            <p className="text-xs font-medium uppercase tracking-wide text-muted">{t(`${labelPrefix ?? "kpi"}.${k}` as never)}</p>
            <p className="mt-1 text-2xl font-semibold tabular-nums">{formatKpi(k, kpi.value)}</p>
            <div className="mt-0.5 min-h-4"><Delta kpi={kpi} /></div>
          </Card>
        );
      })}
    </div>
  );
}

export function ChartCard({ title, children, note }: { title: string; children: React.ReactElement; note?: string }) {
  return (
    <Card>
      <h3 className="text-sm font-medium">{title}</h3>
      {note && <p className="text-xs text-muted">{note}</p>}
      <div className="mt-2 h-56 w-full" role="img" aria-label={title}>
        <ResponsiveContainer width="100%" height="100%">{children}</ResponsiveContainer>
      </div>
    </Card>
  );
}

export function label(bucket: string, hourly: boolean): string {
  return hourly ? bucket.slice(5, 16) : bucket.slice(5);
}

/** Standard chart set: utilisation, arrivals vs late, requests and escalations, delay reports. Pass the ones a view needs. */
export function SeriesCharts({ view, show }: { view: InsightsView; show: ("utilisation" | "arrivals" | "requests" | "delays" | "wait")[] }) {
  const t = useTranslations("insights");
  const hourly = view.period.bucket === "hour";
  const data = view.series.map((s) => ({ ...s, label: label(s.bucket, hourly) }));
  const axis = <XAxis dataKey="label" minTickGap={24} fontSize={11} />;
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {show.includes("utilisation") && (
        <ChartCard title={t("chart.utilisation")}>
          <AreaChart data={data}>
            <CartesianGrid strokeDasharray="3 3" />
            {axis}
            <YAxis unit="%" domain={[0, 100]} fontSize={11} width={44} />
            <Tooltip />
            <Area type="monotone" dataKey="utilisation_pct" stroke={PALETTE[0]} fill={PALETTE[0]} fillOpacity={0.3} name={t("kpi.utilisation_pct")} />
          </AreaChart>
        </ChartCard>
      )}
      {show.includes("arrivals") && (
        <ChartCard title={t("chart.arrivals")}>
          <BarChart data={data}>
            <CartesianGrid strokeDasharray="3 3" />
            {axis}
            <YAxis allowDecimals={false} fontSize={11} width={40} />
            <Tooltip />
            <Legend />
            <Bar dataKey="arrivals" fill={PALETTE[2]} name={t("chart.arrivalsLabel")} />
            <Bar dataKey="late" fill={PALETTE[4]} name={t("chart.lateLabel")} />
          </BarChart>
        </ChartCard>
      )}
      {show.includes("requests") && (
        <ChartCard title={t("chart.requests")}>
          <BarChart data={data}>
            <CartesianGrid strokeDasharray="3 3" />
            {axis}
            <YAxis allowDecimals={false} fontSize={11} width={40} />
            <Tooltip />
            <Legend />
            <Bar dataKey="requests" fill={PALETTE[0]} name={t("kpi.requests")} />
            <Bar dataKey="escalations" fill={PALETTE[4]} name={t("kpi.escalations")} />
          </BarChart>
        </ChartCard>
      )}
      {show.includes("delays") && (
        <ChartCard title={t("chart.delays")}>
          <BarChart data={data}>
            <CartesianGrid strokeDasharray="3 3" />
            {axis}
            <YAxis allowDecimals={false} fontSize={11} width={40} />
            <Tooltip />
            <Legend />
            <Bar dataKey="delay_reports" fill={PALETTE[1]} name={t("kpi.delay_reports")} />
            <Bar dataKey="no_shows" fill={PALETTE[3]} name={t("chart.noShows")} />
          </BarChart>
        </ChartCard>
      )}
      {show.includes("wait") && (
        <ChartCard title={t("chart.wait")}>
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" />
            {axis}
            <YAxis unit=" min" fontSize={11} width={56} />
            <Tooltip />
            <Line type="monotone" dataKey="avg_wait_min" stroke={PALETTE[5]} strokeWidth={2} dot={false} name={t("kpi.avg_wait_min")} />
          </LineChart>
        </ChartCard>
      )}
    </div>
  );
}

export function ShareTable({ title, rows, nameOf, extra }: { title: string; rows: { key: string; count: number; share: number; avg_delay_min?: number; avg_resolution_min?: number }[]; nameOf: (k: string) => string; extra?: "delay" | "resolution" }) {
  const t = useTranslations("insights");
  if (rows.length === 0) return null;
  return (
    <Card>
      <h3 className="mb-2 text-sm font-medium">{title}</h3>
      <table className="w-full text-left text-sm">
        <caption className="sr-only">{title}</caption>
        <thead className="text-xs uppercase tracking-wide text-muted">
          <tr>
            <th scope="col" className="py-1 pr-2 font-medium">{t("table.name")}</th>
            <th scope="col" className="py-1 pr-2 font-medium">{t("table.count")}</th>
            <th scope="col" className="py-1 pr-2 font-medium">{t("table.share")}</th>
            {extra && <th scope="col" className="py-1 font-medium">{extra === "delay" ? t("table.avgDelay") : t("table.avgResolution")}</th>}
          </tr>
        </thead>
        <tbody className="divide-y divide-border/60">
          {rows.map((r) => (
            <tr key={r.key}>
              <td className="py-1.5 pr-2 font-medium">{nameOf(r.key)}</td>
              <td className="py-1.5 pr-2 tabular-nums">{r.count}</td>
              <td className="py-1.5 pr-2">
                <div className="flex items-center gap-2">
                  <div className="h-2 w-20 rounded-full bg-background" aria-hidden="true"><div className="h-2 rounded-full" style={{ width: `${Math.max(2, r.share)}%`, background: PALETTE[0] }} /></div>
                  <span className="text-xs tabular-nums text-muted">{r.share}%</span>
                </div>
              </td>
              {extra && <td className="py-1.5 tabular-nums">{Math.round((extra === "delay" ? r.avg_delay_min : r.avg_resolution_min) ?? 0)} min</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

/** Weekday by hour utilisation. Each cell has the number as text; colour only reinforces it. */
export function Heatmap({ rows }: { rows: { dow: number; hour: number; utilisation_pct: number }[] }) {
  const t = useTranslations("insights");
  if (rows.length === 0) return null;
  const hours = [...new Set(rows.map((r) => r.hour))].sort((a, b) => a - b);
  const by = new Map(rows.map((r) => [`${r.dow}-${r.hour}`, r.utilisation_pct]));
  return (
    <Card>
      <h3 className="text-sm font-medium">{t("heatmap.title")}</h3>
      <p className="mb-2 text-xs text-muted">{t("heatmap.hint")}</p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[34rem] border-separate border-spacing-1 text-center text-[11px]">
          <caption className="sr-only">{t("heatmap.title")}</caption>
          <thead>
            <tr>
              <th scope="col" className="w-10" />
              {hours.map((h) => <th key={h} scope="col" className="font-medium text-muted">{String(h).padStart(2, "0")}</th>)}
            </tr>
          </thead>
          <tbody>
            {[1, 2, 3, 4, 5, 6, 7].map((d) => (
              <tr key={d}>
                <th scope="row" className="pr-1 text-right font-medium text-muted">{t(`weekday.${d}`)}</th>
                {hours.map((h) => {
                  const v = by.get(`${d}-${h}`);
                  return (
                    <td key={h} className="rounded px-0.5 py-1 tabular-nums" style={v === undefined ? undefined : { background: `color-mix(in srgb, var(--accent) ${Math.round(heatOpacity(v) * 100)}%, transparent)` }} title={v === undefined ? "—" : `${v}%`}>
                      {v === undefined ? "" : Math.round(v)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

export function CsvMenu({ view, tables, extra, filenameBase }: { view: ViewKey; tables: string[]; extra: Record<string, string | null | undefined>; filenameBase: string }) {
  const t = useTranslations("insights");
  const [busy, setBusy] = React.useState<string | null>(null);
  const get = async (table: string) => {
    setBusy(table);
    try {
      await downloadCsv(`/analytics/views/${view}/export.csv${qs({ table, ...extra })}`, `${filenameBase}-${table}.csv`);
    } catch (e) {
      toast.error(errorMessage(e, t("csvFailed")));
    } finally {
      setBusy(null);
    }
  };
  return (
    <div className="flex flex-wrap items-center gap-2" role="group" aria-label={t("csv")}>
      <span className="text-xs text-muted">{t("csv")}</span>
      {tables.map((x) => (
        <Button key={x} size="sm" variant="outline" disabled={busy !== null} onClick={() => get(x)}>
          <Download className="size-3.5" aria-hidden="true" />
          {t(`csvTable.${x}` as never)}
        </Button>
      ))}
    </div>
  );
}

export function NarrativeCard({ view, range, extra, enabled = true }: { view: ViewKey; range: RangeKey; extra?: Record<string, string | null | undefined>; enabled?: boolean }) {
  const t = useTranslations("insights");
  const locale = useLocale();
  const q = useNarrative(view, range, locale === "hi" ? "hi" : "en", extra, enabled);
  return (
    <Card className="flex items-start gap-3">
      <Sparkles className="mt-0.5 size-5 shrink-0 text-accent" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="font-medium">{t("narrative.title")}</h3>
          <Badge tone="neutral">{t("narrative.aiNote")}</Badge>
        </div>
        {q.isLoading ? (
          <div role="status" aria-label={t("loading")} className="mt-2 space-y-2"><Skeleton className="h-4 w-full" /><Skeleton className="h-4 w-4/5" /></div>
        ) : q.error ? (
          <p className="mt-1 text-sm text-muted">{t("narrative.unavailable")}</p>
        ) : q.data?.ai_available && q.data.text ? (
          <div className="mt-1 space-y-1 text-sm">
            {q.data.text.split("\n").filter(Boolean).map((l, i) => <p key={i}>{l}</p>)}
            <p className="pt-1 text-xs text-muted">{t("narrative.footer", { model: q.data.model ?? "—" })}</p>
          </div>
        ) : (
          <p className="mt-1 text-sm text-muted">{t("narrative.unavailable")}</p>
        )}
      </div>
    </Card>
  );
}

export function EmptyNote({ children }: { children: React.ReactNode }) {
  return <p className="rounded-md border border-dashed border-border px-4 py-8 text-center text-sm text-muted">{children}</p>;
}
