"use client";

import { useLocale, useTranslations } from "next-intl";
import * as React from "react";
import { MoveOptionsDialog } from "@/components/facility/move-options-dialog";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Badge } from "@/components/ui/card";
import { QueryState, KeyValue } from "@/components/facility/common";
import { useFacQuery } from "@/lib/fac";
import type { SlotDetail } from "@/lib/facility-types";
import { formatDateTime } from "@/lib/format";
import { styleFor } from "@/lib/slot-state";
import { hhmm } from "@/lib/time";

const ISO = /^\d{4}-\d{2}-\d{2}T/;

function Section({ title, data, keys, locale, label }: { title: string; data: Record<string, unknown> | null; keys: string[]; locale: string; label: (k: string) => string }) {
  if (!data) return null;
  const rows = keys.filter((k) => data[k] !== undefined && data[k] !== null && data[k] !== "");
  if (rows.length === 0) return null;
  return (
    <section aria-label={title}>
      <h3 className="mb-2 text-sm font-semibold">{title}</h3>
      <dl className="grid grid-cols-2 gap-3">
        {rows.map((k) => {
          const v = data[k];
          const text = typeof v === "string" && ISO.test(v) ? formatDateTime(v, locale) : typeof v === "boolean" ? (v ? "✓" : "—") : String(v);
          return (
            <KeyValue key={k} label={label(k)}>
              {text}
            </KeyValue>
          );
        })}
      </dl>
    </section>
  );
}

export function SlotDetailDrawer({ slotId, state, tz, onClose, canMove }: { slotId: string | null; state?: string; tz: string; onClose: () => void; canMove?: boolean }) {
  const [picking, setPicking] = React.useState(false);
  const t = useTranslations("facility");
  const locale = useLocale();
  const q = useFacQuery<SlotDetail>(slotId ? `/schedule/slots/${slotId}` : null);
  const d = q.data;
  const appt = d?.appointment as { id?: string; status?: string } | null | undefined;
  const ship = d?.shipment as { id?: string; code?: string } | null | undefined;
  const movable = !!canMove && !!appt?.id && !!ship?.id && (appt.status === "CONFIRMED" || appt.status === "PENDING_CONFIRMATION");
  const label = (k: string) => (t.has(`fields.${k}` as "fields.code") ? t(`fields.${k}` as "fields.code") : k);

  return (
    <Dialog
      open={!!slotId}
      drawer
      onClose={onClose}
      title={d ? `${d.slot.dock_code ?? ""} ${hhmm(d.slot.start, tz)}–${hhmm(d.slot.end, tz)}`.trim() : t("schedule.detail")}
      description={d?.slot.code}
    >
      <QueryState isLoading={q.isLoading} isError={q.isError} onRetry={() => q.refetch()}>
        {d && (
          <div className="space-y-6">
            <div className="flex flex-wrap items-center gap-2">
              {state && <Badge tone="accent">{t(`state.${styleFor(state).labelKey}`)}</Badge>}
              <Badge>{d.slot.slot_status}</Badge>
              {d.slot.block_reason && <span className="text-sm text-muted">{d.slot.block_reason}</span>}
            </div>
            {!d.appointment && <p className="text-sm text-muted">{t("schedule.noBooking")}</p>}
            {movable && (
              <Button variant="outline" onClick={() => setPicking(true)}>
                {t("move.moveTo")}
              </Button>
            )}
            <Section title={t("schedule.booking")} data={d.appointment} locale={locale} label={label}
              keys={["code", "appointment_status", "booking_source", "booked_at", "confirmed_at", "cancelled_at", "cancellation_reason", "warehouse_confirmation_ref"]} />
            <Section title={t("schedule.shipment")} data={d.shipment} locale={locale} label={label}
              keys={["code", "customer_name", "product_category", "load_weight_kg", "pallet_count", "required_dock_type", "priority_code", "expected_unload_min", "current_status"]} />
            <Section title={t("schedule.driver")} data={d.driver} locale={locale} label={label}
              keys={["driver_name", "phone", "preferred_language", "carrier_name"]} />
            <Section title={t("schedule.vehicle")} data={d.vehicle} locale={locale} label={label}
              keys={["registration_number", "capacity_kg", "refrigeration_capable"]} />
            {d.eta && d.eta.ts && (
              <section aria-label={t("schedule.eta")}>
                <h3 className="mb-2 text-sm font-semibold">{t("schedule.eta")}</h3>
                <dl className="grid grid-cols-3 gap-3">
                  <KeyValue label={t("fields.eta_ts")}>{formatDateTime(d.eta.ts, locale)}</KeyValue>
                  <KeyValue label={t("fields.eta_source")}>{d.eta.source ?? "—"}</KeyValue>
                  <KeyValue label={t("fields.eta_confidence")}>{d.eta.confidence ?? "—"}</KeyValue>
                </dl>
              </section>
            )}
            <section aria-label={t("schedule.history")}>
              <h3 className="mb-2 text-sm font-semibold">{t("schedule.history")}</h3>
              {d.history.length === 0 ? (
                <p className="text-sm text-muted">{t("schedule.noHistory")}</p>
              ) : (
                <ol className="space-y-2 border-l border-border pl-4">
                  {d.history.map((h, i) => (
                    <li key={i} className="text-sm">
                      <span className="font-medium">{String(h.appointment_status ?? h.status ?? "")}</span>
                      {h.shipment_code ? <span> · {String(h.shipment_code)}</span> : null}
                      <span className="block text-xs text-muted">
                        {formatDateTime((h.cancelled_at ?? h.booked_at) as string | undefined, locale)}
                        {h.cancellation_reason ? ` — ${String(h.cancellation_reason)}` : ""}
                      </span>
                    </li>
                  ))}
                </ol>
              )}
            </section>
          </div>
        )}
      </QueryState>
      {movable && picking && (
        <MoveOptionsDialog
          open
          onClose={() => {
            setPicking(false);
            onClose();
          }}
          appointmentId={appt!.id!}
          shipmentId={ship!.id!}
          shipmentCode={ship!.code ?? ""}
          tz={tz}
        />
      )}
    </Dialog>
  );
}
