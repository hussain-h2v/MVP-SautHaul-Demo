"use client";

import { useTranslations } from "next-intl";
import * as React from "react";
import { RequireFacility } from "@/components/facility/facility-context";
import { DatePicker, QueryState } from "@/components/facility/common";
import { ScheduleGrid, SlotLegend } from "@/components/facility/schedule-grid";
import { SlotDetailDrawer } from "@/components/facility/slot-detail-drawer";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/page-header";
import { qs, useFacQuery } from "@/lib/fac";
import type { FacilitySummary, Schedule } from "@/lib/facility-types";
import { ZOOM_LEVELS } from "@/lib/schedule-layout";
import { todayIn } from "@/lib/time";

function nearest(dates: string[], target: string): string | null {
  if (dates.length === 0) return null;
  const t = new Date(target).getTime();
  return [...dates].sort((a, b) => Math.abs(new Date(a).getTime() - t) - Math.abs(new Date(b).getTime() - t))[0];
}

function ScheduleView({ facility }: { facility: FacilitySummary }) {
  const t = useTranslations("facility");
  const tz = facility.timezone;
  const [date, setDate] = React.useState(() => todayIn(tz));
  const [zoom, setZoom] = React.useState<number>(60);
  const [selected, setSelected] = React.useState<{ id: string; state: string } | null>(null);

  const schedule = useFacQuery<Schedule>(`/schedule${qs({ facility_id: facility.id, date })}`, { refetchInterval: 60_000 });
  const dates = useFacQuery<string[]>(`/slots/dates${qs({ facility_id: facility.id })}`);
  const empty = !!schedule.data && schedule.data.docks.every((d) => d.slots.length === 0);
  const jump = empty && dates.data ? nearest(dates.data.filter((d) => d !== date), date) : null;

  return (
    <>
      <PageHeader
        title={t("schedule.title")}
        description={t("schedule.description")}
        actions={
          <div className="flex items-center gap-1" role="group" aria-label={t("schedule.zoom")}>
            {ZOOM_LEVELS.map((z) => (
              <Button key={z} size="sm" variant={zoom === z ? "primary" : "outline"} aria-pressed={zoom === z} onClick={() => setZoom(z)}>
                {z}px/h
              </Button>
            ))}
          </div>
        }
      />
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <DatePicker value={date} onChange={setDate} tz={tz} dates={dates.data} />
        <p className="text-xs text-muted">{t("schedule.moveNote")}</p>
      </div>
      <div className="mb-4">
        <SlotLegend />
      </div>
      <QueryState isLoading={schedule.isLoading} isError={schedule.isError} onRetry={() => schedule.refetch()}>
        {schedule.data && schedule.data.docks.length === 0 ? (
          <p className="rounded-md border border-dashed border-border py-10 text-center text-sm text-muted">{t("schedule.noDocks")}</p>
        ) : (
          schedule.data && (
            <>
              {empty && (
                <div role="status" className="mb-3 flex flex-wrap items-center gap-3 rounded-md border border-border bg-accent-soft px-4 py-3 text-sm">
                  <span>{t("schedule.noSlotsOnDate", { date })}</span>
                  {jump && (
                    <Button size="sm" variant="outline" onClick={() => setDate(jump)}>
                      {t("schedule.jumpTo", { date: jump })}
                    </Button>
                  )}
                </div>
              )}
              <ScheduleGrid schedule={schedule.data} pxPerHour={zoom} selectedSlotId={selected?.id ?? null} onSelect={(s) => setSelected({ id: s.slot_id, state: s.state })} />
            </>
          )
        )}
      </QueryState>
      <SlotDetailDrawer slotId={selected?.id ?? null} state={selected?.state} tz={tz} onClose={() => setSelected(null)} />
    </>
  );
}

export default function SchedulePage() {
  return <RequireFacility>{(f) => <ScheduleView key={f.id} facility={f} />}</RequireFacility>;
}
