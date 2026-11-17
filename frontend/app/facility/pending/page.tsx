"use client";

import { Clock } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";
import { PriorityBadge } from "@/components/admin/badges";
import { QueryState } from "@/components/facility/common";
import { RequireFacility } from "@/components/facility/facility-context";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge, Card } from "@/components/ui/card";
import { ConfirmDialog, Dialog } from "@/components/ui/dialog";
import { Field, FormError, Textarea } from "@/components/ui/fields";
import { MoveOptionsDialog } from "@/components/facility/move-options-dialog";
import { api } from "@/lib/api";
import { describeMoveError, type Tr } from "@/lib/problems";
import { qs, useCap, useFacMutation, useFacQuery, useNow } from "@/lib/fac";
import type { FacilitySummary, PendingAppointment } from "@/lib/facility-types";
import { formatDateTime } from "@/lib/format";
import { countdown, hhmm, minutesUntil } from "@/lib/time";

function PendingView({ facility }: { facility: FacilitySummary }) {
  const t = useTranslations("facility.pending");
  const tf = useTranslations("facility");
  const locale = useLocale();
  const now = useNow(1000);
  const canWrite = useCap("day_schedule") === "W";
  const q = useFacQuery<PendingAppointment[]>(`/appointments/pending${qs({ facility_id: facility.id })}`, { refetchInterval: 30_000 });
  const [confirming, setConfirming] = React.useState<PendingAppointment | null>(null);
  const [rejecting, setRejecting] = React.useState<PendingAppointment | null>(null);
  const [reason, setReason] = React.useState("");
  const [err, setErr] = React.useState<string | null>(null);
  const [suggesting, setSuggesting] = React.useState<PendingAppointment | null>(null);

  const confirm = useFacMutation((a: PendingAppointment) => api(`/appointments/${a.appointment_id}/confirm`, { method: "POST" }), {
    success: t("confirmed"),
    onSuccess: () => setConfirming(null),
    onError: (e) => {
      setConfirming(null);
      setErr(describeMoveError(e, tf as unknown as Tr));
    },
  });
  const reject = useFacMutation(
    (v: { a: PendingAppointment; reason: string }) =>
      api(`/appointments/${v.a.appointment_id}/reject`, { method: "POST", body: { reason: v.reason } }),
    {
      success: t("rejected"),
      onSuccess: () => {
        setRejecting(null);
        setReason("");
      },
      onError: (e) => setErr(describeMoveError(e, tf as unknown as Tr)),
    },
  );

  const items = q.data ?? [];

  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <p className="sr-only" role="status" aria-live="polite">
        {t("count", { count: items.length })}
      </p>
      <FormError message={err} />
      <QueryState isLoading={q.isLoading} isError={q.isError} onRetry={() => q.refetch()} empty={items.length === 0} emptyText={t("empty")}>
        <ul className="grid gap-4 lg:grid-cols-2">
          {items.map((a) => {
            const mins = minutesUntil(a.expires_at, now);
            const expired = mins < 0;
            return (
              <li key={a.appointment_id}>
                <Card className="space-y-3">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <p className="font-semibold">{a.shipment_code}</p>
                      <p className="text-sm text-muted">
                        {a.carrier_name ?? "—"}
                        {a.driver_name ? ` · ${a.driver_name}` : ""}
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      <PriorityBadge value={a.priority_code} />
                      <Badge tone={expired ? "danger" : mins < 5 ? "warning" : "neutral"}>
                        <Clock className="mr-1 size-3" aria-hidden="true" />
                        {expired ? t("expired") : t("expiresIn", { time: countdown(a.expires_at, now) })}
                      </Badge>
                    </div>
                  </div>
                  <dl className="grid grid-cols-2 gap-3 text-sm">
                    <div>
                      <dt className="text-xs uppercase tracking-wider text-muted">{t("slot")}</dt>
                      <dd>
                        {a.dock_code} · {hhmm(a.slot_start_ts, facility.timezone)}–{hhmm(a.slot_end_ts, facility.timezone)}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-xs uppercase tracking-wider text-muted">{t("bookedAt")}</dt>
                      <dd>{formatDateTime(a.booked_at, locale)}</dd>
                    </div>
                  </dl>
                  <p className="rounded-md bg-accent-soft px-3 py-2 text-sm">{t(`reason.${a.reason}`)}</p>
                  {canWrite && (
                    <div className="flex flex-wrap gap-2">
                      <Button onClick={() => { setErr(null); setConfirming(a); }}>{t("confirm")}</Button>
                      <Button variant="outline" onClick={() => { setErr(null); setRejecting(a); }}>
                        {t("reject")}
                      </Button>
                      <Button variant="outline" title={t("suggestHint")} onClick={() => { setErr(null); setSuggesting(a); }}>
                        {t("suggest")}
                      </Button>
                    </div>
                  )}
                </Card>
              </li>
            );
          })}
        </ul>
      </QueryState>

      {suggesting && (
        <MoveOptionsDialog
          open
          onClose={() => setSuggesting(null)}
          appointmentId={suggesting.appointment_id}
          shipmentId={suggesting.shipment_id}
          shipmentCode={suggesting.shipment_code}
          tz={facility.timezone}
          successKey="suggested"
        />
      )}

      <ConfirmDialog
        open={!!confirming}
        onClose={() => setConfirming(null)}
        title={t("confirmTitle")}
        message={confirming ? t("confirmMessage", { shipment: confirming.shipment_code, slot: `${confirming.dock_code} ${hhmm(confirming.slot_start_ts, facility.timezone)}` }) : ""}
        confirmLabel={t("confirm")}
        pending={confirm.isPending}
        onConfirm={() => confirming && confirm.mutate(confirming)}
      />

      <Dialog
        open={!!rejecting}
        onClose={() => setRejecting(null)}
        title={t("rejectTitle")}
        description={rejecting ? t("rejectMessage", { shipment: rejecting.shipment_code }) : undefined}
        footer={
          <>
            <Button variant="outline" onClick={() => setRejecting(null)}>
              {t("cancel")}
            </Button>
            <Button
              className="bg-danger text-white"
              disabled={reason.trim().length < 3 || reject.isPending}
              onClick={() => rejecting && reject.mutate({ a: rejecting, reason: reason.trim() })}
            >
              {t("reject")}
            </Button>
          </>
        }
      >
        <Field label={t("rejectReason")} htmlFor="reject-reason" hint={t("rejectReasonHint")}>
          <Textarea id="reject-reason" value={reason} onChange={(e) => setReason(e.target.value)} />
        </Field>
      </Dialog>
    </>
  );
}

export default function PendingPage() {
  return <RequireFacility>{(f) => <PendingView key={f.id} facility={f} />}</RequireFacility>;
}
