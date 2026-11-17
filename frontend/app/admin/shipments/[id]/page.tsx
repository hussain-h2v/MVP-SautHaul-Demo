"use client";

import { CircleDot, FileText, MapPin, PackageCheck, PackageX, Send, Truck, UserCheck, Warehouse } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import { useParams } from "next/navigation";
import * as React from "react";
import { OfferBadge, PriorityBadge, StatusBadge } from "@/components/admin/badges";
import { CancelShipmentDialog, OfferShipmentDialog, ShipmentFormDialog } from "@/components/admin/shipment-forms";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge, Card, Skeleton } from "@/components/ui/card";
import type { Shipment, ShipmentTimeline, TimelineEvent, TimelineKind } from "@/lib/admin-types";
import { formatDate, formatDateTime } from "@/lib/format";
import { errorMessage, useDetail } from "@/lib/use-api";

const icons: Record<TimelineKind, React.ComponentType<{ className?: string; "aria-hidden"?: boolean }>> = {
  created: FileText,
  offered: Send,
  assigned: UserCheck,
  eta: MapPin,
  appointment: Warehouse,
  checkin: Truck,
  unload: PackageCheck,
  cancelled: PackageX,
  audit: CircleDot,
};

function Fact({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wider text-muted">{label}</dt>
      <dd className="mt-1 text-sm">{value || "—"}</dd>
    </div>
  );
}

function TimelineList({ events, locale }: { events: TimelineEvent[]; locale: string }) {
  const k = useTranslations("enums.kind");
  return (
    <ol className="relative ml-3 border-l border-border">
      {events.map((e, i) => {
        const Icon = icons[e.kind] ?? CircleDot;
        return (
          <li key={i} className="mb-6 ml-6 last:mb-0">
            <span className="absolute -left-3.5 grid size-7 place-items-center rounded-full border border-border bg-surface text-accent">
              <Icon className="size-3.5" aria-hidden={true} />
            </span>
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-sm font-medium">{e.title}</p>
              <Badge>{k.has(e.kind as "created") ? k(e.kind as "created") : e.kind}</Badge>
            </div>
            {e.detail && <p className="mt-0.5 text-sm text-muted">{e.detail}</p>}
            <p className="mt-0.5 text-xs text-muted">
              <time dateTime={e.ts}>{formatDateTime(e.ts, locale)}</time>
              {e.actor ? ` · ${e.actor}` : ""}
            </p>
          </li>
        );
      })}
    </ol>
  );
}

export default function ShipmentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const t = useTranslations("admin.shipments");
  const c = useTranslations("common");
  const d = useTranslations("enums.dock");
  const locale = useLocale();
  const { data: s, isLoading, error, refetch } = useDetail<Shipment>(`/shipments/${id}`);
  const timeline = useDetail<ShipmentTimeline>(`/shipments/${id}/timeline`);
  const [editing, setEditing] = React.useState(false);
  const [cancelling, setCancelling] = React.useState(false);
  const [offering, setOffering] = React.useState(false);
  const crumbs = [{ label: t("title"), href: "/admin/shipments" }, { label: s?.code ?? "…" }];

  if (isLoading) return <Skeleton className="h-64 w-full" />;
  if (error || !s) {
    return (
      <>
        <PageHeader title={t("title")} breadcrumbs={crumbs} />
        <p role="alert" className="text-danger">
          {errorMessage(error, c("loadFailed"))}
        </p>
        <Button variant="outline" className="mt-3" onClick={() => void refetch()}>
          {c("retry")}
        </Button>
      </>
    );
  }
  const closed = s.current_status === "CANCELLED" || s.current_status === "COMPLETED";
  const events = timeline.data?.events.filter((e) => e.kind !== "audit") ?? [];
  const audit = timeline.data?.events.filter((e) => e.kind === "audit") ?? [];

  return (
    <>
      <PageHeader
        title={`${s.code} · ${s.customer_name}`}
        description={s.order_reference}
        breadcrumbs={crumbs}
        actions={
          <>
            <StatusBadge value={s.current_status} />
            <Button variant="outline" disabled={closed} onClick={() => setOffering(true)}>
              {t("offerAction")}
            </Button>
            <Button variant="outline" disabled={closed} onClick={() => setEditing(true)}>
              {c("edit")}
            </Button>
            <Button variant="outline" disabled={closed} onClick={() => setCancelling(true)}>
              {c("cancelAction")}
            </Button>
          </>
        }
      />
      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <h2 className="mb-4 font-semibold">{t("details")}</h2>
          <dl className="grid gap-4 sm:grid-cols-3">
            <Fact label={t("facility")} value={<Link className="text-accent hover:underline" href={`/admin/facilities/${s.destination_facility_id}`}>{s.facility_name}</Link>} />
            <Fact label={t("origin")} value={`${s.origin_name}, ${s.origin_city}`} />
            <Fact label={t("goods")} value={s.product_category} />
            <Fact label={t("weight")} value={`${s.load_weight_kg} kg`} />
            <Fact label={t("pallets")} value={s.pallet_count} />
            <Fact label={t("dockType")} value={d(s.required_dock_type)} />
            <Fact label={t("priority")} value={<PriorityBadge value={s.priority_code} />} />
            <Fact label={t("unload")} value={`${s.expected_unload_min} ${c("min")}`} />
            <Fact label={t("temperature")} value={s.temperature_control_required ? c("yes") : c("no")} />
            <Fact label={t("requestedDate")} value={formatDate(s.requested_date, locale)} />
            <Fact label={t("originalEta")} value={formatDateTime(s.original_eta_ts, locale)} />
            <Fact label={t("latestEta")} value={formatDateTime(s.latest_eta_ts, locale)} />
          </dl>
        </Card>
        <Card>
          <h2 className="mb-4 font-semibold">{t("assignment")}</h2>
          <dl className="space-y-4">
            <Fact label={t("offer")} value={<OfferBadge value={s.offer_status} />} />
            {s.offer_decline_reason && <Fact label={t("declineReason")} value={s.offer_decline_reason} />}
            <Fact label={t("carrier")} value={s.carrier_name} />
            <Fact label={t("driver")} value={s.driver_name} />
          </dl>
          <h3 className="mb-2 mt-6 text-xs font-medium uppercase tracking-wider text-muted">{t("threads")}</h3>
          {timeline.data?.threads.length ? (
            <ul className="flex flex-wrap gap-2">
              {timeline.data.threads.map((th) => (
                <li key={th.id}>
                  <Badge tone="accent" title={th.status}>
                    {th.code} · {th.status}
                  </Badge>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted">{t("noThreads")}</p>
          )}
        </Card>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <Card>
          <h2 className="mb-5 font-semibold">{t("timeline")}</h2>
          {timeline.isLoading ? (
            <Skeleton className="h-32 w-full" />
          ) : timeline.error ? (
            <p role="alert" className="text-sm text-danger">
              {errorMessage(timeline.error, c("loadFailed"))}
            </p>
          ) : events.length === 0 ? (
            <p className="text-sm text-muted">{t("noEvents")}</p>
          ) : (
            <TimelineList events={events} locale={locale} />
          )}
        </Card>
        <Card>
          <h2 className="mb-5 font-semibold">{t("auditTrail")}</h2>
          {audit.length === 0 ? <p className="text-sm text-muted">{t("noAudit")}</p> : <TimelineList events={audit} locale={locale} />}
        </Card>
      </div>

      {editing && <ShipmentFormDialog open onClose={() => setEditing(false)} shipment={s} />}
      <CancelShipmentDialog shipment={cancelling ? s : null} onClose={() => setCancelling(false)} />
      <OfferShipmentDialog shipment={offering ? s : null} onClose={() => setOffering(false)} />
    </>
  );
}
