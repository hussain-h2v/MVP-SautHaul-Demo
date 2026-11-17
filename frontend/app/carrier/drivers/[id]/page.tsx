"use client";

import { Sparkles } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useParams } from "next/navigation";
import * as React from "react";
import { StatusBadge } from "@/components/admin/badges";
import { DriverFormDialog, VerifyDialog } from "@/components/carrier/driver-forms";
import { KeyValue, TableShell, td, th } from "@/components/facility/common";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge, Card, Skeleton } from "@/components/ui/card";
import { languageLabel } from "@/lib/carrier";
import type { DriverDetail } from "@/lib/carrier-types";
import { useMe } from "@/lib/auth";
import { formatDateTime } from "@/lib/format";
import { errorMessage, useDetail } from "@/lib/use-api";

export default function DriverProfilePage() {
  const { id } = useParams<{ id: string }>();
  const t = useTranslations("carrier.drivers");
  const c = useTranslations("common");
  const locale = useLocale();
  const { data: user } = useMe();
  const canWrite = user?.capabilities.drivers_vehicles === "W";
  const { data: d, isLoading, error, refetch } = useDetail<DriverDetail>(`/drivers/${id}`);
  const [editing, setEditing] = React.useState(false);
  const [verifying, setVerifying] = React.useState(false);

  if (isLoading) return <Skeleton className="h-64 w-full" />;
  if (error || !d) {
    return (
      <div role="alert" className="rounded-md border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger">
        {errorMessage(error, c("loadFailed"))}{" "}
        <button type="button" className="font-medium underline" onClick={() => void refetch()}>
          {c("retry")}
        </button>
      </div>
    );
  }

  return (
    <>
      <PageHeader
        breadcrumbs={[{ label: t("title"), href: "/carrier/drivers" }, { label: d.driver_name }]}
        title={d.driver_name}
        description={d.code}
        actions={
          <>
            <Badge tone={d.verified ? "success" : "warning"}>{d.verified ? t("verified") : t("unverified")}</Badge>
            {canWrite && !d.verified && <Button onClick={() => setVerifying(true)}>{t("verify")}</Button>}
            {canWrite && (
              <Button variant="outline" onClick={() => setEditing(true)}>
                {c("edit")}
              </Button>
            )}
          </>
        }
      />
      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <h2 className="mb-4 text-base font-semibold">{t("profile")}</h2>
          <dl className="grid gap-4 sm:grid-cols-3">
            <KeyValue label={t("phone")}>{d.phone}</KeyValue>
            <KeyValue label={t("whatsapp")}>{d.whatsapp_number ?? "—"}</KeyValue>
            <KeyValue label={t("language")}>{languageLabel(d.preferred_language)}</KeyValue>
            <KeyValue label={t("licence")}>{d.licence_number}</KeyValue>
            <KeyValue label={t("homeBase")}>{d.home_base_city ?? "—"}</KeyValue>
            <KeyValue label={c("status")}>{t(`statuses.${d.driver_status}` as "statuses.ACTIVE")}</KeyValue>
            <KeyValue label={t("whatsappOptIn")}>{d.whatsapp_opt_in ? t("optedIn") : t("optedOut")}</KeyValue>
            <KeyValue label={t("activeShipments")}>{d.active_shipments}</KeyValue>
            <KeyValue label={t("lastActivity")}>{formatDateTime(d.last_activity, locale)}</KeyValue>
          </dl>
        </Card>
        <Card className="flex items-start gap-3">
          <Sparkles className="mt-0.5 size-5 text-accent" aria-hidden="true" />
          <div>
            <h2 className="font-semibold">{t("insightsTitle")}</h2>
            <p className="mt-1 text-sm text-muted">{t("insightsBody")}</p>
          </div>
        </Card>
      </div>
      <h2 className="mb-3 mt-8 text-base font-semibold">{t("history")}</h2>
      {d.history.length === 0 ? (
        <p className="rounded-md border border-dashed border-border py-8 text-center text-sm text-muted">{t("noHistory")}</p>
      ) : (
        <TableShell caption={t("history")}>
          <thead>
            <tr className="border-b border-border">
              <th scope="col" className={th}>{t("shipment")}</th>
              <th scope="col" className={th}>{t("facility")}</th>
              <th scope="col" className={th}>{c("status")}</th>
              <th scope="col" className={th}>{t("plannedEta")}</th>
            </tr>
          </thead>
          <tbody>
            {d.history.map((h) => (
              <tr key={h.code} className="border-b border-border last:border-b-0">
                <td className={`${td} font-mono text-xs`}>{h.code}</td>
                <td className={td}>{h.facility_code ?? "—"}</td>
                <td className={td}><StatusBadge value={h.current_status} /></td>
                <td className={td}>{formatDateTime(h.original_eta_ts, locale)}</td>
              </tr>
            ))}
          </tbody>
        </TableShell>
      )}
      {editing && <DriverFormDialog key="edit" open onClose={() => setEditing(false)} driver={d} />}
      {verifying && <VerifyDialog key="verify" open onClose={() => setVerifying(false)} driver={d} />}
    </>
  );
}
