"use client";

import { Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import * as React from "react";
import { ActiveBadge } from "@/components/admin/badges";
import { CarrierFormDialog } from "@/components/admin/carrier-form";
import { DataTable, RowActions, type Column } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/dialog";
import { api } from "@/lib/api";
import type { Carrier } from "@/lib/admin-types";
import { useApiMutation } from "@/lib/use-api";

export default function CarriersPage() {
  const t = useTranslations("admin.carriers");
  const c = useTranslations("common");
  const [editing, setEditing] = React.useState<Carrier | "new" | null>(null);
  const [toggle, setToggle] = React.useState<Carrier | null>(null);
  const setActive = useApiMutation(
    (x: Carrier) => api<Carrier>(`/carriers/${x.id}`, { method: "PATCH", body: { active_flag: !x.active_flag } }),
    { success: c("saved"), onSuccess: () => setToggle(null) },
  );

  const columns: Column<Carrier>[] = [
    { key: "code", header: t("code"), sortKey: "code", cell: (x) => <span className="font-mono text-xs">{x.code}</span> },
    {
      key: "name",
      header: t("name"),
      sortKey: "carrier_name",
      cell: (x) => (
        <Link href={`/admin/carriers/${x.id}`} className="font-medium text-accent hover:underline">
          {x.carrier_name}
        </Link>
      ),
    },
    {
      key: "contact",
      header: t("contact"),
      cell: (x) => (
        <div className="text-xs">
          <div>{x.contact_email ?? "—"}</div>
          <div className="text-muted">{x.contact_phone ?? ""}</div>
        </div>
      ),
    },
    {
      key: "types",
      header: t("allowedTypes"),
      cell: (x) =>
        x.allowed_vehicle_type_codes.length ? (
          <div className="flex flex-wrap gap-1">
            {x.allowed_vehicle_type_codes.map((v) => (
              <Badge key={v}>{v}</Badge>
            ))}
          </div>
        ) : (
          "—"
        ),
    },
    { key: "drivers", header: t("drivers"), cell: (x) => x.driver_count },
    { key: "vehicles", header: t("vehicles"), cell: (x) => x.vehicle_count },
    { key: "active", header: c("status"), cell: (x) => <ActiveBadge active={x.active_flag} /> },
  ];

  return (
    <>
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          <Button onClick={() => setEditing("new")}>
            <Plus className="size-4" aria-hidden="true" />
            {t("new")}
          </Button>
        }
      />
      <DataTable<Carrier>
        tableId="carriers"
        path="/carriers"
        columns={columns}
        rowKey={(x) => x.id}
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
        actions={(x) => (
          <RowActions>
            <Button variant="ghost" size="sm" onClick={() => setEditing(x)}>
              {c("edit")}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setToggle(x)}>
              {x.active_flag ? c("deactivate") : c("activate")}
            </Button>
          </RowActions>
        )}
      />
      {editing && <CarrierFormDialog open onClose={() => setEditing(null)} carrier={editing === "new" ? undefined : editing} />}
      <ConfirmDialog
        open={!!toggle}
        onClose={() => setToggle(null)}
        onConfirm={() => toggle && setActive.mutate(toggle)}
        pending={setActive.isPending}
        destructive={toggle?.active_flag}
        title={toggle?.active_flag ? t("deactivateTitle") : t("activateTitle")}
        message={toggle?.active_flag ? t("deactivateMessage", { name: toggle?.carrier_name ?? "" }) : t("activateMessage", { name: toggle?.carrier_name ?? "" })}
        confirmLabel={toggle?.active_flag ? c("deactivate") : c("activate")}
      />
    </>
  );
}
