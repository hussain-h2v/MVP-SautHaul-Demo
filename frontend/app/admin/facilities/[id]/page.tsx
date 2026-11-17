"use client";

import { AlertTriangle, Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import { useParams } from "next/navigation";
import * as React from "react";
import { ActiveBadge } from "@/components/admin/badges";
import { ContactFormDialog, FacilityFormDialog } from "@/components/admin/facility-forms";
import { PageHeader } from "@/components/page-header";
import { Badge, Card, Skeleton } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/dialog";
import { api } from "@/lib/api";
import type { FacilityContact, FacilityDetail } from "@/lib/admin-types";
import { errorMessage, useApiMutation, useDetail } from "@/lib/use-api";

function Fact({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wider text-muted">{label}</dt>
      <dd className="mt-1 text-sm">{value || "—"}</dd>
    </div>
  );
}

export default function FacilityDetailPage() {
  const { id } = useParams<{ id: string }>();
  const t = useTranslations("admin.facilities");
  const c = useTranslations("common");
  const { data: f, isLoading, error, refetch } = useDetail<FacilityDetail>(`/facilities/${id}`);
  const [editing, setEditing] = React.useState(false);
  const [contact, setContact] = React.useState<FacilityContact | "new" | null>(null);
  const [removing, setRemoving] = React.useState<FacilityContact | null>(null);
  const remove = useApiMutation((ct: FacilityContact) => api<void>(`/facilities/${id}/contacts/${ct.id}`, { method: "DELETE" }), {
    success: t("contactRemoved"),
    onSuccess: () => setRemoving(null),
  });

  const crumbs = [{ label: t("title"), href: "/admin/facilities" }, { label: f?.facility_name ?? "…" }];

  if (isLoading) return <Skeleton className="h-64 w-full" />;
  if (error || !f) {
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

  return (
    <>
      <PageHeader
        title={f.facility_name}
        description={`${f.code} · ${f.city}, ${f.state}`}
        breadcrumbs={crumbs}
        actions={
          <>
            <ActiveBadge active={f.active_flag} />
            <Button variant="outline" onClick={() => setEditing(true)}>
              {c("edit")}
            </Button>
          </>
        }
      />
      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <h2 className="mb-4 font-semibold">{t("details")}</h2>
          <dl className="grid gap-4 sm:grid-cols-2">
            <Fact label={t("address")} value={f.address} />
            <Fact label={t("timezone")} value={f.timezone} />
            <Fact label={t("hours")} value={`${f.open_time}–${f.close_time}`} />
            <Fact label={t("docks")} value={f.dock_count} />
            <Fact label={t("grace")} value={`${f.checkin_grace_min} ${c("min")}`} />
            <Fact label={t("unload")} value={`${f.default_unload_min} ${c("min")}`} />
            <div className="sm:col-span-2">
              <Fact label={t("notes")} value={f.notes} />
            </div>
          </dl>
        </Card>
        <Card>
          <h2 className="mb-2 font-semibold">{t("docks")}</h2>
          <p className="text-4xl font-semibold">{f.dock_count}</p>
          <p className="mt-1 text-sm text-muted">{t("docksHint")}</p>
        </Card>
      </div>

      <Card className="mt-6">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-semibold">{t("contacts")}</h2>
          <Button size="sm" onClick={() => setContact("new")}>
            <Plus className="size-4" aria-hidden="true" />
            {t("addContact")}
          </Button>
        </div>
        {f.contacts.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted">{t("noContacts")}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <caption className="sr-only">{t("contacts")}</caption>
              <thead>
                <tr className="border-b border-border text-left text-xs uppercase tracking-wider text-muted">
                  <th scope="col" className="px-3 py-2 font-medium">{t("contactRole")}</th>
                  <th scope="col" className="px-3 py-2 font-medium">{t("contactName")}</th>
                  <th scope="col" className="px-3 py-2 font-medium">{t("email")}</th>
                  <th scope="col" className="px-3 py-2 font-medium">{t("phone")}</th>
                  <th scope="col" className="px-3 py-2 font-medium">{c("status")}</th>
                  <th scope="col" className="px-3 py-2"><span className="sr-only">{c("actions")}</span></th>
                </tr>
              </thead>
              <tbody>
                {f.contacts.map((ct) => (
                  <tr key={ct.id} className="border-b border-border last:border-0">
                    <td className="px-3 py-2">{ct.contact_role}</td>
                    <td className="px-3 py-2 font-medium">{ct.contact_name}</td>
                    <td className="px-3 py-2">
                      {ct.missing_email || !ct.email ? (
                        <Badge tone="warning">
                          <AlertTriangle className="mr-1 size-3" aria-hidden="true" />
                          {t("missingEmail")}
                        </Badge>
                      ) : (
                        ct.email
                      )}
                    </td>
                    <td className="px-3 py-2">{ct.phone ?? "—"}</td>
                    <td className="px-3 py-2"><ActiveBadge active={ct.active_flag} /></td>
                    <td className="px-3 py-2 text-right">
                      <Button variant="ghost" size="sm" onClick={() => setContact(ct)}>{c("edit")}</Button>
                      {ct.active_flag && (
                        <Button variant="ghost" size="sm" onClick={() => setRemoving(ct)}>{c("deactivate")}</Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {editing && <FacilityFormDialog open onClose={() => setEditing(false)} facility={f} />}
      {contact && (
        <ContactFormDialog open onClose={() => setContact(null)} facilityId={f.id} contact={contact === "new" ? undefined : contact} />
      )}
      <ConfirmDialog
        open={!!removing}
        onClose={() => setRemoving(null)}
        onConfirm={() => removing && remove.mutate(removing)}
        pending={remove.isPending}
        destructive
        title={t("removeContactTitle")}
        message={t("removeContactMessage", { name: removing?.contact_name ?? "" })}
        confirmLabel={c("deactivate")}
      />
    </>
  );
}
