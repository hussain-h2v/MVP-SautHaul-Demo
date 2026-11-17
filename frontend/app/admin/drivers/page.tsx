"use client";

import { useLocale, useTranslations } from "next-intl";
import { DataTable, type Column } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/card";
import type { Carrier, DriverRow, Page } from "@/lib/admin-types";
import { formatDateTime, LANGUAGES } from "@/lib/format";
import { useOptions } from "@/lib/use-api";

export default function DriversPage() {
  const t = useTranslations("admin.drivers");
  const c = useTranslations("common");
  const locale = useLocale();
  const carriers = useOptions<Page<{ id: string; carrier_name: string }> | Page<Carrier>>("/carriers?limit=200");

  const columns: Column<DriverRow>[] = [
    { key: "code", header: t("code"), sortKey: "code", cell: (d) => <span className="font-mono text-xs">{d.code}</span> },
    {
      key: "name",
      header: t("name"),
      sortKey: "driver_name",
      cell: (d) => (
        <div>
          <div className="font-medium">{d.driver_name}</div>
          <div className="text-xs text-muted">{d.whatsapp_number ?? d.phone}</div>
        </div>
      ),
    },
    { key: "carrier", header: t("carrier"), sortKey: "carrier_name", cell: (d) => d.carrier_name },
    { key: "lang", header: t("language"), cell: (d) => d.preferred_language.toUpperCase() },
    {
      key: "whatsapp",
      header: t("whatsapp"),
      cell: (d) => (
        <div className="flex flex-wrap gap-1">
          <Badge tone={d.whatsapp_opt_in ? "success" : "neutral"}>{d.whatsapp_opt_in ? t("optedIn") : t("optedOut")}</Badge>
          <Badge tone={d.verified ? "success" : "warning"}>{d.verified ? t("verified") : t("unverified")}</Badge>
        </div>
      ),
    },
    { key: "status", header: c("status"), cell: (d) => <Badge>{d.driver_status}</Badge> },
    { key: "active", header: t("activeShipments"), cell: (d) => d.active_shipments },
    { key: "last", header: t("lastActivity"), cell: (d) => <span className="text-xs">{formatDateTime(d.last_activity, locale)}</span> },
  ];

  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <DataTable<DriverRow>
        tableId="drivers"
        path="/drivers"
        columns={columns}
        rowKey={(d) => d.id}
        defaultSort="code"
        searchPlaceholder={t("search")}
        filters={[
          {
            key: "carrier_id",
            label: t("carrier"),
            type: "select",
            options: (carriers.data?.items ?? []).map((x) => ({ value: x.id, label: x.carrier_name })),
          },
          { key: "language", label: t("language"), type: "select", options: LANGUAGES.map((l) => ({ value: l, label: l.toUpperCase() })) },
          {
            key: "opt_in",
            label: t("whatsappOptIn"),
            type: "select",
            options: [
              { value: "true", label: t("optedIn") },
              { value: "false", label: t("optedOut") },
            ],
          },
          {
            key: "verified",
            label: t("verification"),
            type: "select",
            options: [
              { value: "true", label: t("verified") },
              { value: "false", label: t("unverified") },
            ],
          },
        ]}
      />
    </>
  );
}
