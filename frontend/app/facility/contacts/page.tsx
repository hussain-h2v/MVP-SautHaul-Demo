"use client";

import { AlertTriangle, Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import { useQueryClient } from "@tanstack/react-query";
import * as React from "react";
import { ContactFormDialog } from "@/components/admin/facility-forms";
import { QueryState, TableShell, td, th } from "@/components/facility/common";
import { RequireFacility } from "@/components/facility/facility-context";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/dialog";
import { FormError } from "@/components/ui/fields";
import type { FacilityContact, FacilityDetail } from "@/lib/admin-types";
import { api } from "@/lib/api";
import { apiErrorText, useCap, useFacMutation, useFacQuery } from "@/lib/fac";
import type { FacilitySummary } from "@/lib/facility-types";

function ContactsView({ facility }: { facility: FacilitySummary }) {
  const t = useTranslations("facility.contacts");
  const a = useTranslations("admin.facilities");
  const c = useTranslations("common");
  const qc = useQueryClient();
  const canWrite = useCap("docks_slots_rules") === "W";
  const q = useFacQuery<FacilityDetail>(`/facilities/${facility.id}`);
  const [editing, setEditing] = React.useState<FacilityContact | "new" | null>(null);
  const [removing, setRemoving] = React.useState<FacilityContact | null>(null);
  const [err, setErr] = React.useState<string | null>(null);
  const remove = useFacMutation((ct: FacilityContact) => api<void>(`/facilities/${facility.id}/contacts/${ct.id}`, { method: "DELETE" }), {
    success: a("contactRemoved"),
    onSuccess: () => setRemoving(null),
    onError: (e) => {
      setRemoving(null);
      setErr(apiErrorText(e));
    },
  });
  const contacts = q.data?.contacts ?? [];
  const missing = contacts.filter((x) => x.active_flag && x.missing_email).length;

  return (
    <>
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          canWrite && (
            <Button onClick={() => setEditing("new")}>
              <Plus className="size-4" aria-hidden="true" />
              {a("addContact")}
            </Button>
          )
        }
      />
      {missing > 0 && (
        <div role="status" className="mb-4 flex items-center gap-2 rounded-md border border-amber-500/50 bg-amber-100 px-4 py-3 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-200">
          <AlertTriangle className="size-4 shrink-0" aria-hidden="true" />
          {t("missingEmailBanner", { count: missing })}
        </div>
      )}
      <FormError message={err} />
      <QueryState isLoading={q.isLoading} isError={q.isError} onRetry={() => q.refetch()} empty={contacts.length === 0} emptyText={a("noContacts")}>
        <TableShell caption={t("title")}>
          <thead>
            <tr className="border-b border-border">
              {[a("contactRole"), a("contactName"), a("email"), a("phone"), c("status"), canWrite ? c("actions") : ""].map((h, i) => (
                <th key={i} scope="col" className={th}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {contacts.map((ct) => (
              <tr key={ct.id} className={`border-b border-border last:border-b-0 ${ct.active_flag ? "" : "opacity-60"}`}>
                <td className={td}>{ct.contact_role}</td>
                <td className={`${td} font-medium`}>{ct.contact_name}</td>
                <td className={td}>
                  {ct.email ?? (
                    <Badge tone="warning">
                      <AlertTriangle className="mr-1 size-3" aria-hidden="true" />
                      {a("missingEmail")}
                    </Badge>
                  )}
                </td>
                <td className={td}>{ct.phone ?? "—"}</td>
                <td className={td}>{ct.active_flag ? <Badge tone="success">{c("active")}</Badge> : <Badge>{c("inactive")}</Badge>}</td>
                {canWrite && (
                  <td className={td}>
                    <div className="flex gap-1">
                      <Button size="sm" variant="ghost" onClick={() => setEditing(ct)}>
                        {c("edit")}
                      </Button>
                      {ct.active_flag && (
                        <Button size="sm" variant="ghost" onClick={() => { setErr(null); setRemoving(ct); }}>
                          {c("deactivate")}
                        </Button>
                      )}
                    </div>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </TableShell>
      </QueryState>
      {editing && <ContactFormDialog open onClose={() => { setEditing(null); qc.invalidateQueries({ queryKey: ["fac"] }); }} facilityId={facility.id} contact={editing === "new" ? undefined : editing} />}
      <ConfirmDialog
        open={!!removing}
        onClose={() => setRemoving(null)}
        title={a("removeContactTitle")}
        message={a("removeContactMessage", { name: removing?.contact_name ?? "" })}
        confirmLabel={c("deactivate")}
        destructive
        pending={remove.isPending}
        onConfirm={() => removing && remove.mutate(removing)}
      />
    </>
  );
}

export default function ContactsPage() {
  return <RequireFacility>{(f) => <ContactsView key={f.id} facility={f} />}</RequireFacility>;
}
