"use client";

import { useTranslations } from "next-intl";
import * as React from "react";
import { QueryStateBlock } from "@/components/insights/query-state";
import { ChartCard, CsvMenu, EmptyNote, Heatmap, KpiGrid, NarrativeCard, RangeChips, SeriesCharts, ShareTable } from "@/components/insights/common";
import { Card } from "@/components/ui/card";
import { formatMoney } from "@/lib/ai";
import { useInsightsView, type InsightsView, type RangeKey, type ViewKey } from "@/lib/insights";
import { formatDateTime } from "@/lib/format";

export type ChartKey = "utilisation" | "arrivals" | "requests" | "delays" | "wait";

function Plain({ title, head, rows }: { title: string; head: string[]; rows: (string | number)[][] }) {
  if (rows.length === 0) return null;
  return (
    <Card className="overflow-x-auto">
      <h3 className="mb-2 text-sm font-medium">{title}</h3>
      <table className="w-full text-left text-sm">
        <caption className="sr-only">{title}</caption>
        <thead className="text-xs uppercase tracking-wide text-muted">
          <tr>{head.map((h, i) => <th key={i} scope="col" className="whitespace-nowrap py-1 pr-3 font-medium">{h}</th>)}</tr>
        </thead>
        <tbody className="divide-y divide-border/60">
          {rows.map((r, i) => (
            <tr key={i}>{r.map((c, j) => <td key={j} className={j === 0 ? "py-1.5 pr-3 font-medium" : "py-1.5 pr-3 tabular-nums"}>{c}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

function Tables({ v }: { v: InsightsView }) {
  const t = useTranslations("insights");
  const tb = v.tables;
  const cause = (k: string) => (t.has(`cause.${k}` as never) ? t(`cause.${k}` as never) : k);
  const reason = (k: string) => (t.has(`reason.${k}` as never) ? t(`reason.${k}` as never) : k);
  const req = (k: string) => (t.has(`request.${k}` as never) ? t(`request.${k}` as never) : k);
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {tb.delay_causes && <ShareTable title={t("table.delayCauses")} rows={tb.delay_causes} nameOf={cause} extra="delay" />}
      {tb.escalation_reasons && <ShareTable title={t("table.escalationReasons")} rows={tb.escalation_reasons} nameOf={reason} extra="resolution" />}
      {tb.request_mix && <ShareTable title={t("table.requestMix")} rows={tb.request_mix} nameOf={req} />}
      {tb.by_facility && (
        <Plain title={t("table.byFacility")} head={[t("table.facility"), t("table.available"), t("table.booked"), t("kpi.utilisation_pct")]}
          rows={tb.by_facility.map((r) => [r.facility, Math.round(r.available_min), Math.round(r.booked_min), `${r.utilisation_pct}%`])} />
      )}
      {tb.by_dock && (
        <Plain title={t("table.byDock")} head={[t("table.facility"), t("table.dock"), t("table.type"), t("table.available"), t("table.booked"), t("kpi.utilisation_pct")]}
          rows={tb.by_dock.map((r) => [r.facility, r.dock, r.type, Math.round(r.available_min), Math.round(r.booked_min), `${r.utilisation_pct}%`])} />
      )}
      {tb.dock_events && (
        <Plain title={t("table.dockEvents")} head={[t("table.facility"), t("table.dock"), t("table.type"), t("table.events"), t("table.hours")]}
          rows={tb.dock_events.map((r) => [r.facility, r.dock, r.type.replace(/_/g, " ").toLowerCase(), r.events, r.hours])} />
      )}
      {tb.by_driver && (
        <Plain title={t("table.byDriver")} head={[t("table.driver"), t("table.trips"), t("table.late"), t("table.lateRate"), t("table.avgLate"), t("table.delayReports")]}
          rows={tb.by_driver.map((r) => [`${r.driver} (${r.code})`, r.trips, r.late, `${r.late_rate}%`, `${Math.round(r.avg_late_min)} min`, r.delay_reports])} />
      )}
      {tb.by_lane && (
        <Plain title={t("table.byLane")} head={[t("table.lane"), t("table.trips"), t("table.late"), t("table.lateRate"), t("table.avgLate"), t("table.avgWait")]}
          rows={tb.by_lane.map((r) => [`${r.origin} → ${r.facility}`, r.trips, r.late, `${r.late_rate}%`, `${Math.round(r.avg_late_min)} min`, `${Math.round(r.avg_wait_min)} min`])} />
      )}
    </div>
  );
}

/** One analytics view: period chips, KPI cards, charts, tables, AI briefing and CSV downloads. */
export function ViewPage({ view, kpis, charts, narrative = true, heatmap = false, csv, extra = {}, filenameBase, aiSpend = false, header }: {
  view: ViewKey; kpis: string[]; charts: ChartKey[]; narrative?: boolean; heatmap?: boolean; csv: string[]; extra?: Record<string, string | null | undefined>;
  filenameBase: string; aiSpend?: boolean; header?: React.ReactNode;
}) {
  const t = useTranslations("insights");
  const [range, setRange] = React.useState<RangeKey>("7d");
  const q = useInsightsView(view, range, extra);
  const v = q.data;
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <RangeChips value={range} onChange={setRange} />
        <CsvMenu view={view} tables={csv} extra={{ range, ...extra }} filenameBase={filenameBase} />
      </div>
      {header}
      <QueryStateBlock isLoading={q.isLoading} error={q.error} onRetry={() => q.refetch()}>
        {v && (
          <>
            <p className="text-xs text-muted">{t("periodNote", { from: formatDateTime(v.period.from), to: formatDateTime(v.period.to), bucket: t(`bucket.${v.period.bucket}`) })}</p>
            {aiSpend && v.ai_spend && (
              <section aria-label={t("aiSpend.title")}>
                <h3 className="mb-2 text-sm font-medium">{t("aiSpend.title")}</h3>
                <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
                  {([["today", v.ai_spend.today], ["month", v.ai_spend.month_to_date], ["projected", v.ai_spend.projected_month]] as const).map(([k, val]) => (
                    <Card key={k} className="!p-4">
                      <p className="text-xs font-medium uppercase tracking-wide text-muted">{t(`aiSpend.${k}`)}</p>
                      <p className="mt-1 text-2xl font-semibold tabular-nums">{formatMoney(val)}</p>
                    </Card>
                  ))}
                </div>
              </section>
            )}
            <KpiGrid view={v} keys={kpis} />
            {narrative && <NarrativeCard view={view} range={range} extra={extra} />}
            {v.series.every((s) => s.arrivals + s.requests + s.escalations + s.delay_reports + s.available_min === 0) ? (
              <EmptyNote>{t("noData")}</EmptyNote>
            ) : (
              <>
                <SeriesCharts view={v} show={charts} />
                {heatmap && v.tables.heatmap && <Heatmap rows={v.tables.heatmap} />}
                <Tables v={v} />
              </>
            )}
          </>
        )}
      </QueryStateBlock>
    </div>
  );
}

export { ChartCard };
