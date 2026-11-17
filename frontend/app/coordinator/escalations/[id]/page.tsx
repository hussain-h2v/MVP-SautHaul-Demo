"use client";

import { Phone } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useParams } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";
import { HandoffView } from "@/components/coordinator/handoff-view";
import { describeCoordError, StatusBadge, useCoordText } from "@/components/coordinator/shared";
import { KeyValue, QueryState } from "@/components/facility/common";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, Textarea } from "@/components/ui/fields";
import { api } from "@/lib/api";
import { useCoordMutation, useCoordQuery } from "@/lib/coord";
import type { Escalation } from "@/lib/coord-types";
import { useCap } from "@/lib/fac";
import { formatDateTime } from "@/lib/format";

export default function EscalationDetailPage() {
  const { id } = useParams<{ id: string }>();
  const t = useTranslations("coord.escalations");
  const nav = useTranslations("nav");
  const { tc, tf } = useCoordText();
  const locale = useLocale();
  const canWork = useCap("escalations_takeover") === "W";
  const q = useCoordQuery<Escalation>(`/coordinator/escalations/${id}`, { refetchInterval: 20_000 });
  const e = q.data;
  const [resolution, setResolution] = React.useState("");
  const base = `/coordinator/escalations/${id}`;
  const fail = (err: unknown) => toast.error(describeCoordError(err, tc, tf));

  const assign = useCoordMutation(() => api(`${base}/assign`, { method: "POST", body: {} }), { success: t("assigned"), onError: fail });
  const start = useCoordMutation(() => api(`${base}/status`, { method: "POST", body: { status: "in_progress" } }), { success: t("started"), onError: fail });
  const resolve = useCoordMutation(() => api(`${base}/resolve`, { method: "POST", body: { resolution: resolution.trim() } }), {
    success: t("resolved"),
    onSuccess: () => setResolution(""),
    onError: fail,
  });
  const closed = e?.status === "resolved";
  const valid = resolution.trim().length >= 3;

  return (
    <>
      <PageHeader
        breadcrumbs={[{ label: nav("escalations"), href: "/coordinator/escalations" }, { label: e?.shipment_code ?? "…" }]}
        title={e ? t("detailTitle", { code: e.shipment_code ?? "—" }) : t("title")}
        description={e ? (t.has(`reasonCode.${e.reason_code}`) ? t(`reasonCode.${e.reason_code}`) : e.reason_code) : undefined}
        actions={e && <StatusBadge status={e.status} />}
      />
      <QueryState isLoading={q.isLoading} isError={q.isError} onRetry={() => q.refetch()}>
        {e && (
          <div className="grid gap-5 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-muted">{t("handoff")}</h2>
              <HandoffView record={e.handoff_record} />
            </Card>
            <div className="space-y-5">
              <Card>
                <dl className="grid grid-cols-2 gap-3">
                  <KeyValue label={t("carrier")}>{e.carrier_name ?? "—"}</KeyValue>
                  <KeyValue label={t("driver")}>{e.driver_name ?? "—"}</KeyValue>
                  <KeyValue label={t("assignee")}>{e.assigned_to?.name ?? t("unassigned")}</KeyValue>
                  <KeyValue label={t("opened")}>{formatDateTime(e.created_at, locale)}</KeyValue>
                  {e.closed_at && <KeyValue label={t("closed")}>{formatDateTime(e.closed_at, locale)}</KeyValue>}
                </dl>
                {e.driver_phone && (
                  <a
                    href={`tel:${e.driver_phone}`}
                    className="mt-4 inline-flex h-10 w-full items-center justify-center gap-2 rounded-md bg-accent px-4 text-sm font-medium text-accent-foreground hover:opacity-90"
                  >
                    <Phone className="size-4" aria-hidden="true" />
                    {t("call", { phone: e.driver_phone })}
                  </a>
                )}
              </Card>
              <Card>
                <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted">{t("work")}</h2>
                {closed ? (
                  <p className="text-sm">
                    <span className="font-medium">{t("resolution")}:</span> {e.resolution}
                  </p>
                ) : (
                  <div className="space-y-3">
                    <div className="flex flex-wrap gap-2">
                      <Button variant="outline" size="sm" disabled={!canWork || assign.isPending} onClick={() => assign.mutate(undefined)}>
                        {t("assignToMe")}
                      </Button>
                      <Button variant="outline" size="sm" disabled={!canWork || e.status !== "open" || start.isPending} onClick={() => start.mutate(undefined)}>
                        {t("markInProgress")}
                      </Button>
                    </div>
                    <Field label={t("resolutionLabel")} htmlFor="resolution" hint={t("resolutionHint")}>
                      <Textarea id="resolution" value={resolution} onChange={(ev) => setResolution(ev.target.value)} />
                    </Field>
                    <Button className="w-full" disabled={!canWork || !valid || resolve.isPending} onClick={() => resolve.mutate(undefined)}>
                      {t("resolve")}
                    </Button>
                  </div>
                )}
              </Card>
            </div>
          </div>
        )}
      </QueryState>
    </>
  );
}
