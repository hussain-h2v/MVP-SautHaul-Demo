"use client";

import { Plus, Upload } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import * as React from "react";
import { OfferBadge, PriorityBadge, StatusBadge } from "@/components/admin/badges";
import { CsvImportDialog } from "@/components/admin/csv-import-dialog";
import {
  CancelShipmentDialog,
  OFFER_STATUSES,
  OfferShipmentDialog,
  PRIORITIES,
  ShipmentFormDialog,
  STATUSES,
} from "@/components/admin/shipment-forms";
import { DataTable, RowActions, type Column } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import type { Carrier, Facility, Page, Shipment } from "@/lib/admin-types";
import { formatDate } from "@/lib/format";
import { useOptions } from "@/lib/use-api";

export default function ShipmentsPage() {
  const t = useTranslations("admin.shipments");
  const c = useTranslations("common");
  const st = useTranslations("enums.status");
  const pr = useTranslations("enums.priority");
  const of = useTranslations("enums.offer");
  const locale = useLocale();
  const facilities = useOptions<Page<Facility>>("/facilities?limit=200");
  const carriers = useOptions<Page<Carrier>>("/carriers?limit=200");
  const [editing, setEditing] = React.useState<Shipment | "new" | null>(null);
  const [cancelling, setCancelling] = React.useState<Shipment | null>(null);
  const [offering, setOffering] = React.useState<Shipment | null>(null);
  const [importing, setImporting] = React.useState(false);

  const columns: Column<Shipment>[] = [
    {
      key: "code",
      header: t("code"),
      sortKey: "code",
      cell: (s) => (
        <Link href={`/admin/shipments/${s.id}`} className="font-mono text-xs font-medium text-accent hover:underline">
          {s.code}
        </Link>
      ),
    },
    {
      key: "order",
      header: t("customer"),
      cell: (s) => (
        <div>
          <div className="font-medium">{s.customer_name}</div>
          <div className="text-xs text-muted">{s.order_reference}</div>
        </div>
      ),
    },
    { key: "facility", header: t("facility"), cell: (s) => <span title={s.facility_name}>{s.facility_code}</span> },
    { key: "carrier", header: t("carrier"), cell: (s) => s.carrier_name ?? <span className="text-muted">—</span> },
    { key: "priority", header: t("priority"), sortKey: "priority_code", cell: (s) => <PriorityBadge value={s.priority_code} /> },
    { key: "status", header: c("status"), cell: (s) => <StatusBadge value={s.current_status} /> },
    { key: "offer", header: t("offer"), cell: (s) => <OfferBadge value={s.offer_status} /> },
    { key: "date", header: t("requestedDate"), sortKey: "requested_date", cell: (s) => <span className="text-xs">{formatDate(s.requested_date, locale)}</span> },
    { key: "unload", header: t("unload"), sortKey: "expected_unload_min", cell: (s) => `${s.expected_unload_min} ${c("min")}` },
  ];

  return (
    <>
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          <>
            <Button variant="outline" onClick={() => setImporting(true)}>
              <Upload className="size-4" aria-hidden="true" />
              {c("importCsv")}
            </Button>
            <Button onClick={() => setEditing("new")}>
              <Plus className="size-4" aria-hidden="true" />
              {t("new")}
            </Button>
          </>
        }
      />
      <DataTable<Shipment>
        tableId="shipments"
        path="/shipments"
        columns={columns}
        rowKey={(s) => s.id}
        defaultSort="code"
        searchPlaceholder={t("search")}
        filters={[
          { key: "status", label: c("status"), type: "select", options: STATUSES.map((x) => ({ value: x, label: st(x) })) },
          { key: "priority", label: t("priority"), type: "select", options: PRIORITIES.map((x) => ({ value: x, label: pr(x) })) },
          { key: "offer_status", label: t("offer"), type: "select", options: OFFER_STATUSES.map((x) => ({ value: x, label: of(x) })) },
          {
            key: "facility_id",
            label: t("facility"),
            type: "select",
            options: (facilities.data?.items ?? []).map((f) => ({ value: f.id, label: f.code })),
          },
          {
            key: "carrier_id",
            label: t("carrier"),
            type: "select",
            options: (carriers.data?.items ?? []).map((x) => ({ value: x.id, label: x.carrier_name })),
          },
        ]}
        actions={(s) => {
          const closed = s.current_status === "CANCELLED" || s.current_status === "COMPLETED";
          return (
            <RowActions>
              <Button variant="ghost" size="sm" onClick={() => setEditing(s)} disabled={closed}>
                {c("edit")}
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setOffering(s)} disabled={closed}>
                {t("offerAction")}
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setCancelling(s)} disabled={closed}>
                {c("cancelAction")}
              </Button>
            </RowActions>
          );
        }}
      />
      {editing && <ShipmentFormDialog open onClose={() => setEditing(null)} shipment={editing === "new" ? undefined : editing} />}
      <CancelShipmentDialog shipment={cancelling} onClose={() => setCancelling(null)} />
      <OfferShipmentDialog shipment={offering} onClose={() => setOffering(null)} />
      <CsvImportDialog
        open={importing}
        onClose={() => setImporting(false)}
        title={t("importTitle")}
        path="/shipments/import"
        required={[
          "order_reference",
          "destination_facility_code",
          "customer_name",
          "origin_name",
          "origin_city",
          "product_category",
          "load_weight_kg",
          "required_dock_type",
          "priority_code",
          "expected_unload_min",
        ]}
        optional={["pallet_count", "temperature_control_required", "requested_date"]}
      />
    </>
  );
}
