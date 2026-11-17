"use client";

import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import * as React from "react";
import { OfferBadge, PriorityBadge, StatusBadge } from "@/components/admin/badges";
import { RespondDialog } from "@/components/carrier/shipment-actions";
import { DataTable, type Column } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import type { Shipment } from "@/lib/admin-types";
import { initialFiltersFromUrl } from "@/lib/carrier";
import { formatDate } from "@/lib/format";

const OFFERS = ["offered", "accepted", "declined"] as const;
const STATUSES = ["PLANNED", "ASSIGNED", "IN_TRANSIT", "AT_GATE", "WAITING", "IN_DOCK", "COMPLETED", "CANCELLED"] as const;

export default function CarrierShipmentsPage() {
  const t = useTranslations("carrier.shipments");
  const o = useTranslations("enums.offer");
  const s = useTranslations("enums.status");
  const d = useTranslations("enums.dock");
  const locale = useLocale();
  const [responding, setResponding] = React.useState<{ shipment: Shipment; mode: "accept" | "decline" } | null>(null);
  const initial = React.useMemo(() => initialFiltersFromUrl(["offer_status", "status"]), []);

  const columns: Column<Shipment>[] = [
    {
      key: "code",
      header: t("shipment"),
      sortKey: "code",
      cell: (r) => (
        <div>
          <Link href={`/carrier/shipments/${r.id}`} className="font-mono text-xs font-medium text-accent hover:underline">
            {r.code}
          </Link>
          <div className="text-xs text-muted">{r.order_reference}</div>
        </div>
      ),
    },
    {
      key: "dest",
      header: t("destination"),
      cell: (r) => (
        <div>
          <div>{r.facility_name}</div>
          <div className="text-xs text-muted">{r.origin_city} → {r.facility_code}</div>
        </div>
      ),
    },
    {
      key: "load",
      header: t("load"),
      cell: (r) => (
        <div>
          <div>{r.product_category}</div>
          <div className="text-xs text-muted">
            {r.load_weight_kg.toLocaleString(locale)} kg · {d(r.required_dock_type)}
            {r.temperature_control_required ? ` · ${t("temp")}` : ""}
          </div>
        </div>
      ),
    },
    { key: "priority", header: t("priority"), sortKey: "priority_code", sortValue: undefined, cell: (r) => <PriorityBadge value={r.priority_code} /> },
    { key: "date", header: t("requested"), sortKey: "requested_date", cell: (r) => <span className="text-xs">{formatDate(r.requested_date, locale)}</span> },
    { key: "status", header: t("status"), sortKey: "current_status", cell: (r) => <StatusBadge value={r.current_status} /> },
    {
      key: "offer",
      header: t("offer"),
      cell: (r) => (
        <div>
          <OfferBadge value={r.offer_status} />
          {r.offer_status === "declined" && r.offer_decline_reason && <div className="mt-1 max-w-48 text-xs text-muted">{r.offer_decline_reason}</div>}
        </div>
      ),
    },
    { key: "team", header: t("assigned"), cell: (r) => (r.driver_name ? <span className="text-sm">{r.driver_name}</span> : <span className="text-xs text-muted">{t("unassigned")}</span>) },
  ];

  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <DataTable<Shipment>
        tableId="carrier-shipments"
        path="/shipments"
        columns={columns}
        rowKey={(r) => r.id}
        defaultSort="code"
        exportable={false}
        initialFilters={initial}
        searchPlaceholder={t("search")}
        filters={[
          { key: "offer_status", label: t("offer"), type: "select", options: OFFERS.map((v) => ({ value: v, label: o(v) })) },
          { key: "status", label: t("status"), type: "select", options: STATUSES.map((v) => ({ value: v, label: s(v) })) },
        ]}
        actions={(r) => (
          <div className="flex justify-end gap-2">
            {r.offer_status === "offered" ? (
              <>
                <Button size="sm" onClick={() => setResponding({ shipment: r, mode: "accept" })}>
                  {t("accept")}
                </Button>
                <Button size="sm" variant="outline" onClick={() => setResponding({ shipment: r, mode: "decline" })}>
                  {t("decline")}
                </Button>
              </>
            ) : r.offer_status === "accepted" && r.current_status !== "COMPLETED" && r.current_status !== "CANCELLED" ? (
              <Link
                href={`/carrier/shipments/${r.id}`}
                className="inline-flex h-8 items-center rounded-md bg-accent px-3 text-sm font-medium text-accent-foreground hover:opacity-90"
              >
                {r.driver_id ? t("manage") : t("assign")}
              </Link>
            ) : (
              <Link href={`/carrier/shipments/${r.id}`} className="inline-flex h-8 items-center rounded-md border border-border px-3 text-sm hover:bg-accent-soft">
                {t("view")}
              </Link>
            )}
          </div>
        )}
      />
      {responding && <RespondDialog shipment={responding.shipment} mode={responding.mode} onClose={() => setResponding(null)} />}
    </>
  );
}
