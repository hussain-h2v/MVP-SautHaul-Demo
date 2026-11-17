"use client";

import { Eye } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";
import { StatusBadge } from "@/components/admin/badges";
import { TimelineDrawer } from "@/components/carrier/timeline";
import { DataTable, type Column } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/card";
import type { DriverRow, Page } from "@/lib/admin-types";
import { initialFiltersFromUrl } from "@/lib/carrier";
import type { HoldState, TrackerRow } from "@/lib/carrier-types";
import { formatDateTime } from "@/lib/format";
import { hhmm } from "@/lib/time";
import { useOptions } from "@/lib/use-api";

const STATUSES = ["PLANNED", "ASSIGNED", "IN_TRANSIT", "AT_GATE", "WAITING", "IN_DOCK", "COMPLETED", "CANCELLED"] as const;
const HOLD_TONE: Record<HoldState, "neutral" | "warning" | "accent"> = {
  none: "neutral",
  held: "warning",
  pending_confirmation: "warning",
  request_waiting: "accent",
  request_suggested: "accent",
};

/** READ ONLY: everything the carrier needs to know about a load, no edit controls anywhere. */
export default function TrackerPage() {
  const t = useTranslations("carrier.tracker");
  const s = useTranslations("enums.status");
  const d = useTranslations("enums.dock");
  const locale = useLocale();
  const [open, setOpen] = React.useState<TrackerRow | null>(null);
  const drivers = useOptions<Page<DriverRow>>("/drivers?limit=200&sort=driver_name");
  const initial = React.useMemo(() => initialFiltersFromUrl(["status", "driver_id"]), []);

  const columns: Column<TrackerRow>[] = [
    {
      key: "code",
      header: t("shipment"),
      cell: (r) => (
        <div>
          <button
            type="button"
            onClick={() => setOpen(r)}
            aria-label={t("openTimeline", { code: r.code })}
            className="inline-flex items-center gap-1 font-mono text-xs font-medium text-accent hover:underline"
          >
            {r.code}
            <Eye className="size-3" aria-hidden="true" />
          </button>
          <div className="text-xs text-muted">{r.order_reference}</div>
        </div>
      ),
    },
    { key: "status", header: t("status"), cell: (r) => <StatusBadge value={r.current_status} /> },
    {
      key: "load",
      header: t("load"),
      cell: (r) => (
        <div className="text-xs">
          <div>{d(r.load.required_dock_type as "ANY")}{r.load.temperature_control_required ? ` · ${t("temp")}` : ""}</div>
          <div className="text-muted">{r.load.weight_kg.toLocaleString(locale)} kg</div>
        </div>
      ),
    },
    {
      key: "team",
      header: t("team"),
      cell: (r) => (
        <div className="text-xs">
          <div>{r.driver?.name ?? <span className="text-muted">{t("noDriver")}</span>}</div>
          <div className="text-muted">{r.vehicle?.registration_number ?? t("noVehicle")}</div>
        </div>
      ),
    },
    { key: "facility", header: t("facility"), cell: (r) => <div className="text-xs"><div>{r.facility.name}</div><div className="font-mono text-muted">{r.facility.code}</div></div> },
    {
      key: "appt",
      header: t("appointment"),
      cell: (r) =>
        r.appointment ? (
          <div className="text-xs">
            <div>
              {r.appointment.slot_code ?? "—"} · {r.appointment.dock_code ?? "—"}
            </div>
            <div className="text-muted">
              {hhmm(r.appointment.start)}–{hhmm(r.appointment.end)}
            </div>
            <Badge className="mt-1">{r.appointment.status}</Badge>
          </div>
        ) : (
          <span className="text-xs text-muted">{t("noAppointment")}</span>
        ),
    },
    {
      key: "eta",
      header: t("eta"),
      cell: (r) => (
        <div className="text-xs">
          <div>{formatDateTime(r.eta.ts, locale)}</div>
          <div className="text-muted">
            {r.eta.source ?? "—"}
            {r.eta.confidence ? ` · ${r.eta.confidence}` : ""}
            {r.eta.declared_by ? ` · ${r.eta.declared_by}` : ""}
          </div>
        </div>
      ),
    },
    {
      key: "checkin",
      header: t("checkin"),
      cell: (r) =>
        r.checkin ? (
          <div className="text-xs">
            <div>{r.checkin.queue_state ?? r.checkin.arrival_state ?? "—"}</div>
            <div className="text-muted">{r.checkin.gate_in_ts ? hhmm(r.checkin.gate_in_ts) : ""}</div>
          </div>
        ) : (
          <span className="text-xs text-muted">{t("notArrived")}</span>
        ),
    },
    {
      key: "state",
      header: t("approval"),
      cell: (r) => (
        <div className="flex flex-col items-start gap-1">
          {r.hold_state !== "none" && <Badge tone={HOLD_TONE[r.hold_state]}>{t(`hold.${r.hold_state}` as "hold.held")}</Badge>}
          {r.escalation && <Badge tone="danger">{t("escalated", { status: r.escalation.status })}</Badge>}
          {r.hold_state === "none" && !r.escalation && <span className="text-xs text-muted">—</span>}
        </div>
      ),
    },
  ];

  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <p className="mb-4 rounded-md border border-border bg-surface px-4 py-2 text-xs text-muted">{t("readOnlyNote")}</p>
      <DataTable<TrackerRow>
        tableId="carrier-tracker"
        path="/carrier/tracker"
        columns={columns}
        rowKey={(r) => r.shipment_id}
        exportable={false}
        initialFilters={initial}
        searchPlaceholder={t("search")}
        filters={[
          { key: "status", label: t("status"), type: "select", options: STATUSES.map((v) => ({ value: v, label: s(v) })) },
          { key: "driver_id", label: t("driver"), type: "select", options: (drivers.data?.items ?? []).map((x) => ({ value: x.id, label: x.driver_name })) },
        ]}
      />
      <TimelineDrawer shipmentId={open?.shipment_id ?? null} code={open?.code ?? ""} onClose={() => setOpen(null)} />
    </>
  );
}
