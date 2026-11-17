"use client";

import { useTranslations } from "next-intl";
import { useParams } from "next/navigation";
import * as React from "react";
import { ActiveBadge } from "@/components/admin/badges";
import { CarrierFormDialog } from "@/components/admin/carrier-form";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge, Card, Skeleton } from "@/components/ui/card";
import type { CarrierDetail } from "@/lib/admin-types";
import { errorMessage, useDetail } from "@/lib/use-api";

function Stat({ label, value, hint }: { label: string; value: number; hint?: string }) {
  return (
    <Card>
      <p className="text-xs font-medium uppercase tracking-wider text-muted">{label}</p>
      <p className="mt-2 text-3xl font-semibold tabular-nums">{value}</p>
      {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
    </Card>
  );
}

export default function CarrierDetailPage() {
  const { id } = useParams<{ id: string }>();
  const t = useTranslations("admin.carriers");
  const c = useTranslations("common");
  const { data: x, isLoading, error, refetch } = useDetail<CarrierDetail>(`/carriers/${id}`);
  const [editing, setEditing] = React.useState(false);
  const crumbs = [{ label: t("title"), href: "/admin/carriers" }, { label: x?.carrier_name ?? "…" }];

  if (isLoading) return <Skeleton className="h-64 w-full" />;
  if (error || !x) {
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
  const done = x.shipments_total ? Math.round((x.shipments_completed / x.shipments_total) * 100) : 0;

  return (
    <>
      <PageHeader
        title={x.carrier_name}
        description={x.code}
        breadcrumbs={crumbs}
        actions={
          <>
            <ActiveBadge active={x.active_flag} />
            <Button variant="outline" onClick={() => setEditing(true)}>
              {c("edit")}
            </Button>
          </>
        }
      />
      <h2 className="mb-3 font-semibold">{t("fleet")}</h2>
      <div className="grid gap-4 sm:grid-cols-2">
        <Stat label={t("drivers")} value={x.driver_count} />
        <Stat label={t("vehicles")} value={x.vehicle_count} />
      </div>
      <h2 className="mb-3 mt-8 font-semibold">{t("performance")}</h2>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label={t("shipmentsTotal")} value={x.shipments_total} />
        <Stat label={t("shipmentsActive")} value={x.shipments_active} />
        <Stat label={t("shipmentsCompleted")} value={x.shipments_completed} hint={t("completionRate", { pct: done })} />
        <Stat label={t("shipmentsCancelled")} value={x.shipments_cancelled} />
      </div>
      <Card className="mt-8">
        <h2 className="mb-3 font-semibold">{t("contactAndRules")}</h2>
        <dl className="grid gap-4 sm:grid-cols-3">
          <div>
            <dt className="text-xs font-medium uppercase tracking-wider text-muted">{t("email")}</dt>
            <dd className="mt-1 text-sm">{x.contact_email ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-xs font-medium uppercase tracking-wider text-muted">{t("phone")}</dt>
            <dd className="mt-1 text-sm">{x.contact_phone ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-xs font-medium uppercase tracking-wider text-muted">{t("allowedTypes")}</dt>
            <dd className="mt-1 flex flex-wrap gap-1">
              {x.allowed_vehicle_type_codes.length ? x.allowed_vehicle_type_codes.map((v) => <Badge key={v}>{v}</Badge>) : "—"}
            </dd>
          </div>
        </dl>
      </Card>
      {editing && <CarrierFormDialog open onClose={() => setEditing(false)} carrier={x} />}
    </>
  );
}
