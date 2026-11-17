"use client";

import { useLocale, useTranslations } from "next-intl";
import * as React from "react";
import { PriorityBadge, StatusBadge } from "@/components/admin/badges";
import { DatePicker, QueryState, TableShell, td, th } from "@/components/facility/common";
import { RequireFacility } from "@/components/facility/facility-context";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/card";
import { qs, useFacQuery } from "@/lib/fac";
import type { FacilitySummary, InboundRow } from "@/lib/facility-types";
import { axisFor, axisWidth, formatAxisLabel, hourTicks, minToPx } from "@/lib/schedule-layout";
import { hhmm, minutesFromDayStart, todayIn } from "@/lib/time";
import { cn } from "@/lib/utils";

function Flags({ row }: { row: InboundRow }) {
  const t = useTranslations("facility.inbound");
  return (
    <span className="flex flex-wrap gap-1">
      {row.late && <Badge tone="danger">{t("late")}</Badge>}
      {!row.late && row.at_risk && <Badge tone="warning">{t("atRisk")}</Badge>}
      {!row.appointment_id && <Badge>{t("noAppointment")}</Badge>}
    </span>
  );
}

function Timeline({ rows, facility, date }: { rows: InboundRow[]; facility: FacilitySummary; date: string }) {
  const t = useTranslations("facility.inbound");
  const tz = facility.timezone;
  const px = 70;
  const points = rows.flatMap((r) => {
    const out: { startMin: number; endMin: number }[] = [];
    for (const iso of [r.eta_ts, r.slot_start_ts]) if (iso) {
      const m = minutesFromDayStart(iso, date, tz);
      out.push({ startMin: m, endMin: m });
    }
    return out;
  });
  const axis = axisFor(facility.open_time, facility.close_time, points);
  const width = axisWidth(axis, px);
  return (
    <div className="overflow-x-auto rounded-xl border border-border bg-surface">
      <div style={{ width: 180 + width }} role="table" aria-label={t("timeline")}>
        <div role="row" className="flex border-b border-border">
          <div role="columnheader" className="sticky left-0 z-10 w-[180px] shrink-0 bg-surface px-3 py-2 text-xs font-medium text-muted">
            {t("shipment")}
          </div>
          <div role="presentation" className="relative h-8" style={{ width }}>
            {hourTicks(axis).map((m) => (
              <span key={m} className="absolute top-2 -translate-x-1/2 text-[11px] tabular-nums text-muted" style={{ left: minToPx(m, axis, px) }}>
                {formatAxisLabel(m)}
              </span>
            ))}
          </div>
        </div>
        {rows.map((r) => {
          const eta = r.eta_ts ? minToPx(minutesFromDayStart(r.eta_ts, date, tz), axis, px) : null;
          const slot = r.slot_start_ts ? minToPx(minutesFromDayStart(r.slot_start_ts, date, tz), axis, px) : null;
          return (
            <div key={r.shipment_id} role="row" className="flex border-b border-border last:border-b-0">
              <div role="rowheader" className="sticky left-0 z-10 w-[180px] shrink-0 bg-surface px-3 py-2">
                <p className="text-sm font-medium">{r.shipment_code}</p>
                <p className="truncate text-xs text-muted">{r.carrier_name ?? "—"}</p>
              </div>
              <div role="cell" className="relative h-14" style={{ width }} aria-label={`${r.shipment_code}: ETA ${hhmm(r.eta_ts, tz)}, ${r.slot_start_ts ? `slot ${hhmm(r.slot_start_ts, tz)}` : t("noAppointment")}`}>
                {hourTicks(axis).map((m) => (
                  <span key={m} aria-hidden="true" className="absolute inset-y-0 w-px bg-border/70" style={{ left: minToPx(m, axis, px) }} />
                ))}
                {eta !== null && slot !== null && (
                  <span aria-hidden="true" className={cn("absolute top-1/2 h-0.5 -translate-y-1/2", r.late ? "bg-danger" : "bg-accent/50")} style={{ left: Math.min(eta, slot), width: Math.abs(slot - eta) }} />
                )}
                {slot !== null && (
                  <span title={t("slotStart")} aria-hidden="true" className="absolute top-1/2 h-8 w-1.5 -translate-x-1/2 -translate-y-1/2 rounded bg-accent" style={{ left: slot }} />
                )}
                {eta !== null && (
                  <span title={t("eta")} aria-hidden="true" className={cn("absolute top-1/2 size-3.5 -translate-x-1/2 -translate-y-1/2 rotate-45 border-2 border-surface", r.late ? "bg-danger" : r.at_risk ? "bg-amber-500" : "bg-success")} style={{ left: eta }} />
                )}
              </div>
            </div>
          );
        })}
      </div>
      <p className="border-t border-border px-3 py-2 text-xs text-muted">{t("timelineLegend")}</p>
    </div>
  );
}

function InboundView({ facility }: { facility: FacilitySummary }) {
  const t = useTranslations("facility.inbound");
  const locale = useLocale();
  const tz = facility.timezone;
  const [date, setDate] = React.useState(() => todayIn(tz));
  const [view, setView] = React.useState<"table" | "timeline">("table");
  const q = useFacQuery<InboundRow[]>(`/inbound${qs({ facility_id: facility.id, date })}`, { refetchInterval: 60_000 });
  const rows = q.data ?? [];

  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <DatePicker value={date} onChange={setDate} tz={tz} />
        <div role="group" aria-label={t("view")} className="flex gap-1">
          {(["table", "timeline"] as const).map((v) => (
            <Button key={v} size="sm" variant={view === v ? "primary" : "outline"} aria-pressed={view === v} onClick={() => setView(v)}>
              {t(`view_${v}`)}
            </Button>
          ))}
        </div>
      </div>
      <QueryState isLoading={q.isLoading} isError={q.isError} onRetry={() => q.refetch()} empty={rows.length === 0} emptyText={t("empty")}>
        {view === "timeline" ? (
          <Timeline rows={rows} facility={facility} date={date} />
        ) : (
          <TableShell caption={t("title")}>
            <thead>
              <tr className="border-b border-border">
                {[t("shipment"), t("carrier"), t("priority"), t("load"), t("status"), t("eta"), t("source"), t("slot"), t("flags")].map((h) => (
                  <th key={h} scope="col" className={th}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.shipment_id} className="border-b border-border last:border-b-0">
                  <td className={`${td} font-medium`}>{r.shipment_code}</td>
                  <td className={td}>
                    {r.carrier_name ?? "—"}
                    {r.driver_name && <span className="block text-xs text-muted">{r.driver_name}</span>}
                  </td>
                  <td className={td}>
                    <PriorityBadge value={r.priority_code} />
                  </td>
                  <td className={td}>{r.required_dock_type}</td>
                  <td className={td}>
                    <StatusBadge value={r.current_status} />
                  </td>
                  <td className={`${td} tabular-nums`}>{r.eta_ts ? new Intl.DateTimeFormat(locale === "hi" ? "hi-IN" : "en-IN", { timeZone: tz, hour: "2-digit", minute: "2-digit", day: "2-digit", month: "short" }).format(new Date(r.eta_ts)) : "—"}</td>
                  <td className={td}>
                    {r.eta_source ?? "—"}
                    {r.eta_confidence && <span className="block text-xs text-muted">{r.eta_confidence}</span>}
                  </td>
                  <td className={td}>{r.slot_code ? `${r.dock_code ?? ""} ${hhmm(r.slot_start_ts, tz)}` : "—"}</td>
                  <td className={td}>
                    <Flags row={r} />
                  </td>
                </tr>
              ))}
            </tbody>
          </TableShell>
        )}
      </QueryState>
    </>
  );
}

export default function InboundPage() {
  return <RequireFacility>{(f) => <InboundView key={f.id} facility={f} />}</RequireFacility>;
}
