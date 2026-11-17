"use client";

import { CircleDot, FileText, MapPin, PackageCheck, PackageX, Send, Truck, UserCheck, Warehouse } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";
import { Dialog } from "@/components/ui/dialog";
import { Badge, Skeleton } from "@/components/ui/card";
import type { ShipmentTimeline, TimelineEvent, TimelineKind } from "@/lib/admin-types";
import { formatDateTime } from "@/lib/format";
import { useDetail } from "@/lib/use-api";

const icons: Record<TimelineKind, React.ComponentType<{ className?: string; "aria-hidden"?: boolean }>> = {
  created: FileText,
  offered: Send,
  assigned: UserCheck,
  eta: MapPin,
  appointment: Warehouse,
  checkin: Truck,
  unload: PackageCheck,
  cancelled: PackageX,
  audit: CircleDot,
};

export function TimelineList({ events }: { events: TimelineEvent[] }) {
  const k = useTranslations("enums.kind");
  const locale = useLocale();
  return (
    <ol className="relative ml-3 border-l border-border">
      {events.map((e, i) => {
        const Icon = icons[e.kind] ?? CircleDot;
        return (
          <li key={i} className="mb-6 ml-6 last:mb-0">
            <span className="absolute -left-3.5 grid size-7 place-items-center rounded-full border border-border bg-surface text-accent">
              <Icon className="size-3.5" aria-hidden={true} />
            </span>
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-sm font-medium">{e.title}</p>
              <Badge>{k.has(e.kind as "created") ? k(e.kind as "created") : e.kind}</Badge>
            </div>
            {e.detail && <p className="mt-0.5 text-sm text-muted">{e.detail}</p>}
            <p className="mt-0.5 text-xs text-muted">
              <time dateTime={e.ts}>{formatDateTime(e.ts, locale)}</time>
              {e.actor ? ` · ${e.actor}` : ""}
            </p>
          </li>
        );
      })}
    </ol>
  );
}

/** Read-only drawer with the full shipment timeline (planned, assigned, ETA history, appointments, check-in, unload). */
export function TimelineDrawer({ shipmentId, code, onClose }: { shipmentId: string | null; code: string; onClose: () => void }) {
  const t = useTranslations("carrier.tracker");
  const c = useTranslations("common");
  const q = useDetail<ShipmentTimeline>(shipmentId ? `/shipments/${shipmentId}/timeline` : null);
  return (
    <Dialog open={!!shipmentId} onClose={onClose} drawer title={t("timelineTitle", { code })} description={t("timelineHint")}>
      {q.isLoading && (
        <div role="status" aria-label={c("loading")} className="space-y-3">
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-2/3" />
        </div>
      )}
      {q.isError && (
        <p role="alert" className="text-sm text-danger">
          {c("loadFailed")}{" "}
          <button type="button" className="font-medium underline" onClick={() => void q.refetch()}>
            {c("retry")}
          </button>
        </p>
      )}
      {q.data && (q.data.events.length ? <TimelineList events={q.data.events} /> : <p className="text-sm text-muted">{t("noEvents")}</p>)}
    </Dialog>
  );
}
