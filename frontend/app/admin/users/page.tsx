"use client";

import { UserPlus } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";
import { UserStatusBadge } from "@/components/admin/badges";
import { InviteLinkDialog, ROLES, UserFormDialog } from "@/components/admin/user-forms";
import { DataTable, RowActions, type Column } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/dialog";
import { api } from "@/lib/api";
import type { AdminUser, Carrier, Facility, InvitedUser, Page } from "@/lib/admin-types";
import { useApiMutation, useOptions } from "@/lib/use-api";
import { useQuery } from "@tanstack/react-query";

export default function UsersPage() {
  const t = useTranslations("admin.users");
  const r = useTranslations("enums.role");
  const s = useTranslations("enums.userStatus");
  const c = useTranslations("common");
  const users = useQuery({ queryKey: ["list", "/users"], queryFn: () => api<AdminUser[]>("/users") });
  const facilities = useOptions<Page<Facility>>("/facilities?limit=200");
  const carriers = useOptions<Page<Carrier>>("/carriers?limit=200");
  const [editing, setEditing] = React.useState<AdminUser | "new" | null>(null);
  const [invite, setInvite] = React.useState<InvitedUser | null>(null);
  const [toggle, setToggle] = React.useState<AdminUser | null>(null);
  const [kick, setKick] = React.useState<AdminUser | null>(null);

  const setStatus = useApiMutation(
    (u: AdminUser) => api<AdminUser>(`/users/${u.id}`, { method: "PATCH", body: { status: u.status === "disabled" ? "active" : "disabled" } }),
    { success: c("saved"), onSuccess: () => setToggle(null) },
  );
  const forceLogout = useApiMutation((u: AdminUser) => api<void>(`/users/${u.id}/force-logout`, { method: "POST" }), {
    success: t("loggedOut"),
    onSuccess: () => setKick(null),
  });

  const facName = (id: string) => facilities.data?.items.find((f) => f.id === id)?.code ?? id.slice(0, 6);
  const scope = (u: AdminUser) => {
    if (u.role === "facility_planner") return u.facility_ids.map(facName).join(", ") || "—";
    if (u.role === "carrier_user") return carriers.data?.items.find((x) => x.id === u.carrier_id)?.carrier_name ?? "—";
    return t("allAccess");
  };

  const columns: Column<AdminUser>[] = [
    {
      key: "name",
      header: t("fullName"),
      sortKey: "name",
      sortValue: (u) => u.full_name.toLowerCase(),
      cell: (u) => (
        <div>
          <div className="font-medium">{u.full_name}</div>
          <div className="text-xs text-muted">{u.email}</div>
        </div>
      ),
    },
    { key: "role", header: t("role"), sortKey: "role", sortValue: (u) => u.role, cell: (u) => <Badge tone="accent">{r(u.role)}</Badge> },
    { key: "scope", header: t("scope"), cell: (u) => <span className="text-xs">{scope(u)}</span> },
    { key: "status", header: c("status"), sortKey: "status", sortValue: (u) => u.status, cell: (u) => <UserStatusBadge value={u.status} /> },
  ];

  return (
    <>
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          <Button onClick={() => setEditing("new")}>
            <UserPlus className="size-4" aria-hidden="true" />
            {t("invite")}
          </Button>
        }
      />
      <DataTable<AdminUser>
        tableId="users"
        columns={columns}
        rowKey={(u) => u.id}
        rows={users.data}
        loading={users.isLoading}
        error={users.error}
        onRetry={() => void users.refetch()}
        defaultSort="name"
        searchPlaceholder={t("search")}
        searchText={(u) => `${u.full_name} ${u.email}`}
        clientFilter={(u, f) => (!f.role || u.role === f.role) && (!f.status || u.status === f.status)}
        filters={[
          { key: "role", label: t("role"), type: "select", options: ROLES.map((x) => ({ value: x, label: r(x) })) },
          { key: "status", label: c("status"), type: "select", options: (["active", "invited", "disabled"] as const).map((x) => ({ value: x, label: s(x) })) },
        ]}
        actions={(u) => (
          <RowActions>
            <Button variant="ghost" size="sm" onClick={() => setEditing(u)}>
              {c("edit")}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setToggle(u)}>
              {u.status === "disabled" ? c("enable") : c("disable")}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setKick(u)}>
              {t("forceLogout")}
            </Button>
          </RowActions>
        )}
      />
      {editing && <UserFormDialog open onClose={() => setEditing(null)} user={editing === "new" ? undefined : editing} onInvited={setInvite} />}
      <InviteLinkDialog invite={invite} onClose={() => setInvite(null)} />
      <ConfirmDialog
        open={!!toggle}
        onClose={() => setToggle(null)}
        onConfirm={() => toggle && setStatus.mutate(toggle)}
        pending={setStatus.isPending}
        destructive={toggle?.status !== "disabled"}
        title={toggle?.status === "disabled" ? t("enableTitle") : t("disableTitle")}
        message={toggle?.status === "disabled" ? t("enableMessage", { name: toggle?.full_name ?? "" }) : t("disableMessage", { name: toggle?.full_name ?? "" })}
        confirmLabel={toggle?.status === "disabled" ? c("enable") : c("disable")}
      />
      <ConfirmDialog
        open={!!kick}
        onClose={() => setKick(null)}
        onConfirm={() => kick && forceLogout.mutate(kick)}
        pending={forceLogout.isPending}
        destructive
        title={t("forceLogoutTitle")}
        message={t("forceLogoutMessage", { name: kick?.full_name ?? "" })}
        confirmLabel={t("forceLogout")}
      />
    </>
  );
}
