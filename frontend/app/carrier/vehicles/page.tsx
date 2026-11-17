"use client";

import { Plus, Upload } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";
import { toast } from "sonner";
import { CsvImportDialog } from "@/components/admin/csv-import-dialog";
import { ActiveBadge } from "@/components/admin/badges";
import { VehicleFormDialog } from "@/components/carrier/vehicle-forms";
import { DataTable, type Column } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/dialog";
import { api } from "@/lib/api";
import type { VehicleType } from "@/lib/admin-types";
import type { VehicleRow } from "@/lib/carrier-types";
import { useMe } from "@/lib/auth";
import { errorMessage, useApiMutation, useOptions } from "@/lib/use-api";

export default function CarrierVehiclesPage() {
  const t = useTranslations("carrier.vehicles");
  const c = useTranslations("common");
  const { data: user } = useMe();
  const canWrite = user?.capabilities.drivers_vehicles === "W";
  const types = useOptions<VehicleType[]>("/vehicle-types");
  const [form, setForm] = React.useState<{ vehicle?: VehicleRow } | null>(null);
  const [removing, setRemoving] = React.useState<VehicleRow | null>(null);
  const [importing, setImporting] = React.useState(false);

  const retire = useApiMutation((v: VehicleRow) => api<VehicleRow>(`/vehicles/${v.id}`, { method: "DELETE" }), {
    success: t("retired"),
    onSuccess: () => setRemoving(null),
  });

  const columns: Column<VehicleRow>[] = [
    {
      key: "reg",
      header: t("registration"),
      sortKey: "registration_number",
      cell: (v) => (
        <div>
          <div className="font-medium">{v.registration_number}</div>
          <div className="font-mono text-xs text-muted">{v.code}</div>
        </div>
      ),
    },
    { key: "type", header: t("type"), cell: (v) => <div>{v.vehicle_type_code}<div className="text-xs text-muted">{v.vehicle_type_description}</div></div> },
    { key: "cap", header: t("capacity"), sortKey: "capacity_kg", cell: (v) => <span className="tabular-nums">{v.capacity_kg.toLocaleString()} kg</span> },
    {
      key: "capabilities",
      header: t("capabilities"),
      cell: (v) => (
        <div className="flex flex-wrap gap-1">
          {v.refrigeration_capable && <Badge tone="accent">{t("reefer")}</Badge>}
          {v.heavy_capable && <Badge tone="accent">{t("heavy")}</Badge>}
          {!v.refrigeration_capable && !v.heavy_capable && <span className="text-xs text-muted">{t("standard")}</span>}
        </div>
      ),
    },
    { key: "active", header: c("status"), cell: (v) => <ActiveBadge active={v.active_flag} /> },
    { key: "assigned", header: t("assigned"), cell: (v) => v.assigned_shipments },
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
      <DataTable<VehicleRow>
        tableId="carrier-vehicles"
        path="/vehicles"
        columns={columns}
        rowKey={(v) => v.id}
        defaultSort="registration_number"
        searchPlaceholder={t("search")}
        filters={[
          { key: "active", label: c("status"), type: "select", options: [{ value: "true", label: c("active") }, { value: "false", label: c("inactive") }] },
          { key: "type", label: t("type"), type: "select", options: (types.data ?? []).map((x) => ({ value: x.code, label: `${x.code} · ${x.description}` })) },
        ]}
        actions={
          canWrite
            ? (v) => (
                <div className="flex justify-end gap-1">
                  <Button size="sm" variant="ghost" onClick={() => setForm({ vehicle: v })}>
                    {c("edit")}
                  </Button>
                  {v.active_flag && (
                    <Button size="sm" variant="ghost" onClick={() => setRemoving(v)}>
                      {t("retire")}
                    </Button>
                  )}
                </div>
              )
            : undefined
        }
      />
      {form && <VehicleFormDialog key={form.vehicle?.id ?? "new"} open onClose={() => setForm(null)} vehicle={form.vehicle} />}
      <ConfirmDialog
        open={!!removing}
        onClose={() => setRemoving(null)}
        title={t("retireTitle")}
        message={t("retireMessage", { reg: removing?.registration_number ?? "" })}
        confirmLabel={t("retire")}
        destructive
        pending={retire.isPending}
        onConfirm={() => removing && retire.mutate(removing, { onError: (e) => toast.error(errorMessage(e, c("saveFailed"))) })}
      />
      <CsvImportDialog
        open={importing}
        onClose={() => setImporting(false)}
        title={t("importTitle")}
        path="/vehicles/import"
        required={["vehicle_type_code", "registration_number", "capacity_kg"]}
        optional={["refrigeration_capable", "heavy_capable"]}
      />
    </>
  );
}
