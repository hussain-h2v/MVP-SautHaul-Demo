"use client";

import { Plus, Upload } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import * as React from "react";
import { ActiveBadge } from "@/components/admin/badges";
import { CsvImportDialog } from "@/components/admin/csv-import-dialog";
import { FacilityFormDialog } from "@/components/admin/facility-forms";
import { DataTable, RowActions, type Column } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/dialog";
import { api } from "@/lib/api";
import type { Facility } from "@/lib/admin-types";
import { useApiMutation } from "@/lib/use-api";

export default function FacilitiesPage() {
  const t = useTranslations("admin.facilities");
  const c = useTranslations("common");
  const [editing, setEditing] = React.useState<Facility | "new" | null>(null);
  const [importing, setImporting] = React.useState(false);
  const [toggle, setToggle] = React.useState<Facility | null>(null);
  const setActive = useApiMutation(
    (f: Facility) => api<Facility>(`/facilities/${f.id}`, { method: "PATCH", body: { active_flag: !f.active_flag } }),
    { success: c("saved"), onSuccess: () => setToggle(null) },
  );

  const columns: Column<Facility>[] = [
    { key: "code", header: t("code"), sortKey: "code", cell: (f) => <span className="font-mono text-xs">{f.code}</span> },
    {
      key: "name",
      header: t("name"),
      sortKey: "facility_name",
      cell: (f) => (
        <Link href={`/admin/facilities/${f.id}`} className="font-medium text-accent hover:underline">
          {f.facility_name}
        </Link>
      ),
    },
    { key: "city", header: t("city"), sortKey: "city", cell: (f) => `${f.city}, ${f.state}` },
    { key: "hours", header: t("hours"), cell: (f) => `${f.open_time}–${f.close_time}` },
    { key: "grace", header: t("grace"), cell: (f) => `${f.checkin_grace_min} ${c("min")}` },
    { key: "active", header: c("status"), cell: (f) => <ActiveBadge active={f.active_flag} /> },
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
      <DataTable<Facility>
        tableId="facilities"
        path="/facilities"
        columns={columns}
        rowKey={(f) => f.id}
        defaultSort="code"
        searchPlaceholder={t("search")}
        filters={[
          {
            key: "active",
            label: c("status"),
            type: "select",
            options: [
              { value: "true", label: c("active") },
              { value: "false", label: c("inactive") },
            ],
          },
        ]}
        actions={(f) => (
          <RowActions>
            <Button variant="ghost" size="sm" onClick={() => setEditing(f)}>
              {c("edit")}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setToggle(f)}>
              {f.active_flag ? c("deactivate") : c("activate")}
            </Button>
          </RowActions>
        )}
      />
      {editing && (
        <FacilityFormDialog open onClose={() => setEditing(null)} facility={editing === "new" ? undefined : editing} />
      )}
      <CsvImportDialog
        open={importing}
        onClose={() => setImporting(false)}
        title={t("importTitle")}
        path="/facilities/import"
        required={["code", "facility_name", "city", "state", "timezone", "open_time", "close_time"]}
        optional={["address", "checkin_grace_min", "default_unload_min", "notes"]}
      />
      <ConfirmDialog
        open={!!toggle}
        onClose={() => setToggle(null)}
        onConfirm={() => toggle && setActive.mutate(toggle)}
        pending={setActive.isPending}
        destructive={toggle?.active_flag}
        title={toggle?.active_flag ? t("deactivateTitle") : t("activateTitle")}
        message={toggle?.active_flag ? t("deactivateMessage", { name: toggle?.facility_name ?? "" }) : t("activateMessage", { name: toggle?.facility_name ?? "" })}
        confirmLabel={toggle?.active_flag ? c("deactivate") : c("activate")}
      />
    </>
  );
}
