"use client";

import { useQuery } from "@tanstack/react-query";
import { Lock } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useParams } from "next/navigation";
import * as React from "react";
import { OfferBadge, PriorityBadge, StatusBadge } from "@/components/admin/badges";
import { AssignPanel, RespondDialog } from "@/components/carrier/shipment-actions";
import { TimelineList } from "@/components/carrier/timeline";
import { KeyValue } from "@/components/facility/common";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge, Card, Skeleton } from "@/components/ui/card";
import { api } from "@/lib/api";
import type { Shipment, ShipmentTimeline } from "@/lib/admin-types";
import type { Page } from "@/lib/admin-types";
import type { TrackerRow } from "@/lib/carrier-types";
import { formatDate, formatDateTime } from "@/lib/format";
import { buildQuery } from "@/lib/query";
import { errorMessage, useDetail } from "@/lib/use-api";

export default function CarrierShipmentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const t = useTranslations("carrier.shipments");
  const tr = useTranslations("carrier.tracker");
  const c = useTranslations("common");
  const d = useTranslations("enums.dock");
  const locale = useLocale();
  const { data: s, isLoading, error, refetch } = useDetail<Shipment>(`/shipments/${id}`);
  const timeline = useDetail<ShipmentTimeline>(`/shipments/${id}/timeline`);
  const [mode, setMode] = React.useState<"accept" | "decline" | null>(null);
  const [reassigning, setReassigning] = React.useState(false);

  // Slot and dock allocation comes from facility planners: read-only, via the tracker.
  const tracker = useQuery<Page<TrackerRow>>({
    queryKey: ["carrier", "tracker-one", s?.code],
    queryFn: () => api<Page<TrackerRow>>(`/carrier/tracker${buildQuery({ q: s?.code, limit: 5 })}`),
    enabled: !!s?.code,
  });
  const row = tracker.data?.items.find((r) => r.shipment_id === id);

  if (isLoading) return <Skeleton className="h-64 w-full" />;
  if (error || !s) {
    return (
      <div role="alert" className="rounded-md border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger">
        {errorMessage(error, c("loadFailed"))}{" "}
        <button type="button" className="font-medium underline" onClick={() => void refetch()}>
          {c("retry")}
        </button>
      </div>
    );
  }

  const open = s.current_status !== "COMPLETED" && s.current_status !== "CANCELLED";
  const canAssign = s.offer_status === "accepted" && open && !s.driver_id;
  const canManage = s.offer_status === "accepted" && open && !!s.driver_id;
  const inYard = ["AT_GATE", "WAITING", "IN_DOCK"].includes(s.current_status);

  return (
    <>
      <PageHeader
        breadcrumbs={[{ label: t("title"), href: "/carrier/shipments" }, { label: s.code }]}
        title={`${s.code} · ${s.customer_name}`}
        description={s.order_reference}
        actions={
          <>
            <StatusBadge value={s.current_status} />
            <OfferBadge value={s.offer_status} />
            {s.offer_status === "offered" && (
              <>
                <Button onClick={() => setMode("accept")}>{t("accept")}</Button>
                <Button variant="outline" onClick={() => setMode("decline")}>
                  {t("decline")}
                </Button>
              </>
            )}
          </>
        }
      />
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <Card>
            <h2 className="mb-4 text-base font-semibold">{t("details")}</h2>
            <dl className="grid gap-4 sm:grid-cols-3">
              <KeyValue label={t("destination")}>
                {s.facility_name} <span className="text-muted">({s.facility_code})</span>
              </KeyValue>
              <KeyValue label={t("origin")}>{s.origin_name}, {s.origin_city}</KeyValue>
              <KeyValue label={t("goods")}>{s.product_category}</KeyValue>
              <KeyValue label={t("weight")}>{s.load_weight_kg.toLocaleString(locale)} kg{s.pallet_count != null ? ` · ${s.pallet_count} pallets` : ""}</KeyValue>
              <KeyValue label={t("dockType")}>{d(s.required_dock_type)}{s.temperature_control_required ? ` · ${t("temp")}` : ""}</KeyValue>
              <KeyValue label={t("priority")}><PriorityBadge value={s.priority_code} /></KeyValue>
              <KeyValue label={t("unload")}>{s.expected_unload_min} {c("min")}</KeyValue>
              <KeyValue label={t("requested")}>{formatDate(s.requested_date, locale)}</KeyValue>
              <KeyValue label={t("eta")}>{formatDateTime(s.latest_eta_ts ?? s.original_eta_ts, locale)}</KeyValue>
            </dl>
            {s.offer_status === "declined" && s.offer_decline_reason && (
              <p className="mt-4 rounded-md bg-danger/10 px-3 py-2 text-sm text-danger">{t("declinedBecause", { reason: s.offer_decline_reason })}</p>
            )}
          </Card>

          <Card>
            <div className="mb-3 flex items-center gap-2">
              <Lock className="size-4 text-muted" aria-hidden="true" />
              <h2 className="text-base font-semibold">{t("allocation")}</h2>
              <Badge>{t("readOnly")}</Badge>
            </div>
            <p className="mb-4 text-sm text-muted">{t("allocationHint")}</p>
            {tracker.isLoading ? (
              <Skeleton className="h-16 w-full" />
            ) : row?.appointment ? (
              <dl className="grid gap-4 sm:grid-cols-3">
                <KeyValue label={tr("slot")}>{row.appointment.slot_code ?? "—"}</KeyValue>
                <KeyValue label={tr("dock")}>{row.appointment.dock_code ?? "—"}</KeyValue>
                <KeyValue label={tr("appointmentStatus")}><Badge>{row.appointment.status}</Badge></KeyValue>
                <KeyValue label={tr("window")}>
                  {formatDateTime(row.appointment.start, locale)} – {formatDateTime(row.appointment.end, locale)}
                </KeyValue>
                <KeyValue label={tr("eta")}>
                  {formatDateTime(row.eta.ts, locale)}
                  {row.eta.source ? <span className="block text-xs text-muted">{row.eta.source}{row.eta.confidence ? ` · ${row.eta.confidence}` : ""}</span> : null}
                </KeyValue>
                {row.checkin && <KeyValue label={tr("checkin")}>{row.checkin.queue_state ?? row.checkin.arrival_state ?? "—"}</KeyValue>}
              </dl>
            ) : (
              <p className="text-sm text-muted">{t("noAppointment")}</p>
            )}
          </Card>

          <Card>
            <h2 className="mb-4 text-base font-semibold">{t("timeline")}</h2>
            {timeline.isLoading ? <Skeleton className="h-24 w-full" /> : timeline.data && timeline.data.events.length > 0 ? <TimelineList events={timeline.data.events} /> : <p className="text-sm text-muted">{tr("noEvents")}</p>}
          </Card>
        </div>

        <div className="space-y-6">
          <Card>
            <h2 className="mb-3 text-base font-semibold">{t("team")}</h2>
            <dl className="space-y-3">
              <KeyValue label={t("driver")}>{s.driver_name ?? <span className="text-muted">{t("unassigned")}</span>}</KeyValue>
              <KeyValue label={t("vehicle")}>{row?.vehicle?.registration_number ?? (s.vehicle_id ? "…" : <span className="text-muted">{t("unassigned")}</span>)}</KeyValue>
            </dl>
            {s.offer_status === "offered" && <p className="mt-3 text-sm text-muted">{t("respondFirst")}</p>}
            {s.offer_status === "declined" && <p className="mt-3 text-sm text-muted">{t("declinedNote")}</p>}
            {canManage && !reassigning && (
              <Button variant="outline" className="mt-4" onClick={() => setReassigning(true)}>
                {t("reassign")}
              </Button>
            )}
            {inYard && canManage && <p className="mt-2 text-xs text-muted">{t("inYardNote")}</p>}
          </Card>
          {canAssign && !reassigning && <AssignPanel key="assign" shipment={s} />}
          {reassigning && (
            <>
              <AssignPanel key="reassign" shipment={s} reassign />
              <Button variant="ghost" onClick={() => setReassigning(false)}>
                {c("cancel")}
              </Button>
            </>
          )}
        </div>
      </div>
      <RespondDialog shipment={s} mode={mode} onClose={() => setMode(null)} />
    </>
  );
}
