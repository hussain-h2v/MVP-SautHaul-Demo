"use client";

import { Plus, Upload } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import * as React from "react";
import { toast } from "sonner";
import { CsvImportDialog } from "@/components/admin/csv-import-dialog";
import { DriverFormDialog, VerifyDialog } from "@/components/carrier/driver-forms";
import { DataTable, type Column } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/dialog";
import { api } from "@/lib/api";
import type { DriverRow } from "@/lib/admin-types";
import { initialFiltersFromUrl, LANGUAGE_OPTIONS } from "@/lib/carrier";
import { formatDateTime } from "@/lib/format";
import { errorMessage, useApiMutation } from "@/lib/use-api";
import { useMe } from "@/lib/auth";

const STATUS_TONE: Record<string, "success" | "neutral" | "warning" | "danger"> = {
  ACTIVE: "success",
  OFF_DUTY: "neutral",
  SUSPENDED: "danger",
  INACTIVE: "neutral",
};

export default function CarrierDriversPage() {
  const t = useTranslations("carrier.drivers");
  const c = useTranslations("common");
  const locale = useLocale();
  const { data: user } = useMe();
  const canWrite = user?.capabilities.drivers_vehicles === "W";
  const [form, setForm] = React.useState<{ driver?: DriverRow } | null>(null);
  const [verifying, setVerifying] = React.useState<DriverRow | null>(null);
  const [removing, setRemoving] = React.useState<DriverRow | null>(null);
  const [importing, setImporting] = React.useState(false);
  const initial = React.useMemo(() => initialFiltersFromUrl(["verified", "language", "opt_in"]), []);

  const deactivate = useApiMutation((d: DriverRow) => api<DriverRow>(`/drivers/${d.id}`, { method: "DELETE" }), {
    success: t("deactivated"),
    onSuccess: () => setRemoving(null),
  });

  const columns: Column<DriverRow>[] = [
    {
      key: "name",
      header: t("name"),
      sortKey: "driver_name",
      cell: (d) => (
        <div>
          <Link href={`/carrier/drivers/${d.id}`} className="font-medium text-accent hover:underline">
            {d.driver_name}
          </Link>
          <div className="text-xs text-muted">
            <span className="font-mono">{d.code}</span> · {d.whatsapp_number ?? d.phone}
          </div>
        </div>
      ),
    },
    { key: "lang", header: t("language"), cell: (d) => d.preferred_language.toUpperCase() },
    {
      key: "whatsapp",
      header: t("whatsapp"),
      cell: (d) => (
        <div className="flex flex-wrap gap-1">
          <Badge tone={d.verified ? "success" : "warning"}>{d.verified ? t("verified") : t("unverified")}</Badge>
          <Badge tone={d.whatsapp_opt_in ? "success" : "neutral"}>{d.whatsapp_opt_in ? t("optedIn") : t("optedOut")}</Badge>
        </div>
      ),
    },
    { key: "status", header: c("status"), cell: (d) => <Badge tone={STATUS_TONE[d.driver_status] ?? "neutral"}>{t(`statuses.${d.driver_status}` as "statuses.ACTIVE")}</Badge> },
    { key: "active", header: t("activeShipments"), cell: (d) => d.active_shipments },
    { key: "last", header: t("lastActivity"), cell: (d) => <span className="text-xs">{formatDateTime(d.last_activity, locale)}</span> },
  ];

  return (
    <>
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          canWrite && (
            <>
              <Button variant="outline" onClick={() => setImporting(true)}>
                <Upload className="size-4" aria-hidden="true" />
                {c("importCsv")}
              </Button>
              <Button onClick={() => setForm({})}>
                <Plus className="size-4" aria-hidden="true" />
                {t("new")}
              </Button>
            </>
          )
        }
      />
      <DataTable<DriverRow>
        tableId="carrier-drivers"
        path="/drivers"
        columns={columns}
        rowKey={(d) => d.id}
        defaultSort="driver_name"
        initialFilters={initial}
        searchPlaceholder={t("search")}
        filters={[
          { key: "language", label: t("language"), type: "select", options: LANGUAGE_OPTIONS.map((l) => ({ value: l.code, label: `${l.native} (${l.code.toUpperCase()})` })) },
          { key: "verified", label: t("verification"), type: "select", options: [{ value: "true", label: t("verified") }, { value: "false", label: t("unverified") }] },
          { key: "opt_in", label: t("whatsappOptIn"), type: "select", options: [{ value: "true", label: t("optedIn") }, { value: "false", label: t("optedOut") }] },
        ]}
        actions={
          canWrite
            ? (d) => (
                <div className="flex justify-end gap-1">
                  {!d.verified && (
                    <Button size="sm" variant="outline" onClick={() => setVerifying(d)}>
                      {t("verify")}
                    </Button>
                  )}
                  <Button size="sm" variant="ghost" onClick={() => setForm({ driver: d })}>
                    {c("edit")}
                  </Button>
                  {d.driver_status !== "INACTIVE" && (
                    <Button size="sm" variant="ghost" onClick={() => setRemoving(d)}>
                      {c("deactivate")}
                    </Button>
                  )}
                </div>
              )
            : undefined
        }
      />
      {form && <DriverFormDialog key={form.driver?.id ?? "new"} open onClose={() => setForm(null)} driver={form.driver} />}
      {verifying && <VerifyDialog key={verifying.id} open onClose={() => setVerifying(null)} driver={verifying} />}
      <ConfirmDialog
        open={!!removing}
        onClose={() => setRemoving(null)}
        title={t("deactivateTitle")}
        message={t("deactivateMessage", { name: removing?.driver_name ?? "" })}
        confirmLabel={c("deactivate")}
        destructive
        pending={deactivate.isPending}
        onConfirm={() => removing && deactivate.mutate(removing, { onError: (e) => toast.error(errorMessage(e, c("saveFailed"))) })}
      />
      <CsvImportDialog
        open={importing}
        onClose={() => setImporting(false)}
        title={t("importTitle")}
        path="/drivers/import"
        required={["driver_name", "phone", "preferred_language", "licence_number"]}
        optional={["whatsapp_number", "home_base_city"]}
      />
    </>
  );
}
