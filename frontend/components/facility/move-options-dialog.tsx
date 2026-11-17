"use client";

import { useQuery } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";
import { toast } from "sonner";
import { QueryState } from "@/components/facility/common";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { api } from "@/lib/api";
import { useFacMutation } from "@/lib/fac";
import type { MoveResult, SchedulingOptions } from "@/lib/facility-types";
import { formatDateTime } from "@/lib/format";
import { describeMoveError, describeProblem, type Tr } from "@/lib/problems";
import { hhmm } from "@/lib/time";

/**
 * Keyboard-friendly alternative to drag and drop and the "Suggest another slot" flow: ranked feasible options for
 * the shipment (read-only search, nothing is reserved) and a one-click move of the appointment to the chosen one.
 */
export function MoveOptionsDialog({
  open,
  onClose,
  appointmentId,
  shipmentId,
  shipmentCode,
  tz,
  successKey = "moved",
}: {
  open: boolean;
  onClose: () => void;
  appointmentId: string;
  shipmentId: string;
  shipmentCode: string;
  tz: string;
  successKey?: "moved" | "suggested";
}) {
  const t = useTranslations("facility");
  const tr = t as unknown as Tr;
  const locale = useLocale();
  const q = useQuery<SchedulingOptions>({
    queryKey: ["options", shipmentId],
    queryFn: () => api<SchedulingOptions>("/scheduling/options", { method: "POST", body: { shipment_id: shipmentId, limit: 8 } }),
    enabled: open,
    staleTime: 0,
  });

  const move = useFacMutation(
    (slotIds: string[]) =>
      api<MoveResult>(`/booking/appointments/${appointmentId}/move`, { method: "POST", body: { slot_ids: slotIds } }),
    {
      onSuccess: (res) => {
        toast.success(
          res.appointment_status === "PENDING_CONFIRMATION"
            ? t("move.movedPending")
            : successKey === "suggested"
              ? t("pending.suggested")
              : t("move.moved"),
        );
        onClose();
      },
      onError: (e) => {
        toast.error(describeMoveError(e, tr));
        void q.refetch();
      },
    },
  );

  const d = q.data;
  const rejections = d ? Object.entries(d.rejections).sort((a, b) => b[1] - a[1]) : [];

  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="lg"
      title={t("move.pickerTitle")}
      description={t("move.pickerDescription", { shipment: shipmentCode })}
      footer={
        <Button variant="outline" onClick={onClose} data-autofocus>
          {t("pending.cancel")}
        </Button>
      }
    >
      <QueryState isLoading={q.isLoading} isError={q.isError} onRetry={() => q.refetch()}>
        {d && (
          <div className="space-y-4">
            {d.eta && (
              <p className="text-sm text-muted">
                {t("move.pickerEta", {
                  time: formatDateTime(d.eta.ts, locale),
                  source: d.eta.source,
                  confidence: d.eta.confidence.toLowerCase(),
                })}
                {d.eta.requires_human_review && <span className="ml-2 text-amber-600 dark:text-amber-400">{t("move.pickerReview")}</span>}
              </p>
            )}
            {d.options.length === 0 ? (
              <p className="rounded-md border border-dashed border-border py-8 text-center text-sm text-muted" role="status">
                {t("move.pickerEmpty")}
              </p>
            ) : (
              <ol className="space-y-3" aria-label={t("move.pickerTitle")}>
                {d.options.map((o) => (
                  <li key={o.slot_ids.join("-")} className="rounded-lg border border-border bg-surface p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div>
                        <p className="font-medium">
                          <span className="mr-2 text-xs uppercase tracking-wider text-muted">{t("move.rank", { rank: o.rank })}</span>
                          {o.dock_code} · {formatDateTime(o.start, locale)} → {hhmm(o.end, tz)}
                        </p>
                        <p className="mt-1 text-sm text-muted">{o.explanation}</p>
                      </div>
                      <div className="flex items-center gap-2">
                        {o.needs_planner_approval && <Badge tone="warning">{t("move.approvalBadge")}</Badge>}
                        <Button size="sm" disabled={move.isPending} onClick={() => move.mutate(o.slot_ids)}>
                          {t("move.moveHere")}
                        </Button>
                      </div>
                    </div>
                    <ul className="mt-2 flex flex-wrap gap-1.5">
                      {o.reasons
                        .filter((r) => r !== "NEEDS_PLANNER_APPROVAL")
                        .map((r) => (
                          <li key={r}>
                            <Badge>{describeProblem(r, tr)}</Badge>
                          </li>
                        ))}
                    </ul>
                  </li>
                ))}
              </ol>
            )}
            {rejections.length > 0 && (
              <details className="text-sm">
                <summary className="cursor-pointer font-medium">{t("move.pickerRejections")}</summary>
                <ul className="mt-2 space-y-1 text-muted">
                  {rejections.map(([code, n]) => (
                    <li key={code}>
                      {describeProblem(code, tr)} <span className="tabular-nums">×{n}</span>
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        )}
      </QueryState>
    </Dialog>
  );
}
