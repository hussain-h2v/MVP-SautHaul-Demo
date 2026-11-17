"use client";

import { useTranslations } from "next-intl";
import * as React from "react";
import { useNow } from "@/lib/fac";
import type { Schedule, ScheduleDock, ScheduleSlot } from "@/lib/facility-types";
import { axisFor, axisWidth, formatAxisLabel, hourTicks, layoutSpans, minToPx } from "@/lib/schedule-layout";
import { SLOT_STATES, SLOT_STYLES, styleFor } from "@/lib/slot-state";
import { hhmm, minutesFromDayStart } from "@/lib/time";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/card";

const LABEL_W = 132;
const LANE_H = 52;
const HEADER_H = 32;

interface HoverState {
  slot: ScheduleSlot;
  dock: ScheduleDock;
  x: number;
  y: number;
}

export function SlotLegend() {
  const t = useTranslations("facility");
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-2" aria-label={t("schedule.legend")}>
      {SLOT_STATES.map((s) => (
        <li key={s} className="flex items-center gap-1.5 text-xs">
          <span className={cn("grid size-5 place-items-center rounded", SLOT_STYLES[s].className)} aria-hidden="true">
            {SLOT_STYLES[s].glyph}
          </span>
          {t(`state.${s}`)}
        </li>
      ))}
    </ul>
  );
}

export function ScheduleGrid({
  schedule,
  pxPerHour,
  selectedSlotId,
  onSelect,
}: {
  schedule: Schedule;
  pxPerHour: number;
  selectedSlotId: string | null;
  onSelect: (slot: ScheduleSlot, dock: ScheduleDock) => void;
}) {
  const t = useTranslations("facility");
  const tz = schedule.facility.timezone;
  const now = useNow(60_000);
  const [hover, setHover] = React.useState<HoverState | null>(null);
  const gridRef = React.useRef<HTMLDivElement>(null);

  const rows = React.useMemo(() => {
    const spanned = schedule.docks.map((dock) => ({
      dock,
      spans: dock.slots.map((slot) => ({
        slot,
        startMin: minutesFromDayStart(slot.start, schedule.date, tz),
        endMin: minutesFromDayStart(slot.end, schedule.date, tz),
      })),
    }));
    const axis = axisFor(schedule.facility.open_time, schedule.facility.close_time, spanned.flatMap((r) => r.spans));
    return {
      axis,
      docks: spanned.map((r) => ({ dock: r.dock, placed: layoutSpans(r.spans, axis, pxPerHour) })),
    };
  }, [schedule, tz, pxPerHour]);

  const { axis } = rows;
  const width = axisWidth(axis, pxPerHour);
  const nowMin = minutesFromDayStart(new Date(now).toISOString(), schedule.date, tz);
  const showNow = nowMin >= axis.startMin && nowMin <= axis.endMin;

  const onKeyDown = (e: React.KeyboardEvent) => {
    const target = e.target as HTMLElement;
    if (target.dataset.row === undefined) return;
    const row = Number(target.dataset.row);
    const inRow = (r: number) =>
      Array.from(gridRef.current?.querySelectorAll<HTMLButtonElement>(`button[data-row="${r}"]`) ?? []);
    const current = inRow(row);
    const idx = current.indexOf(target as HTMLButtonElement);
    let next: HTMLElement | undefined;
    if (e.key === "ArrowRight") next = current[idx + 1];
    else if (e.key === "ArrowLeft") next = current[idx - 1];
    else if (e.key === "Home") next = current[0];
    else if (e.key === "End") next = current[current.length - 1];
    else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      const candidates = inRow(row + (e.key === "ArrowDown" ? 1 : -1));
      const start = Number(target.dataset.start);
      next = candidates.sort((a, b) => Math.abs(Number(a.dataset.start) - start) - Math.abs(Number(b.dataset.start) - start))[0];
    } else return;
    e.preventDefault();
    next?.focus();
  };

  const show = (slot: ScheduleSlot, dock: ScheduleDock, el: HTMLElement) => {
    const r = el.getBoundingClientRect();
    setHover({ slot, dock, x: Math.min(r.left, window.innerWidth - 300), y: r.bottom + 6 });
  };

  return (
    <div className="relative">
      <div className="overflow-x-auto rounded-xl border border-border bg-surface" tabIndex={-1}>
        <div
          ref={gridRef}
          role="grid"
          aria-label={t("schedule.gridLabel", { date: schedule.date, facility: schedule.facility.facility_name })}
          aria-rowcount={rows.docks.length + 1}
          onKeyDown={onKeyDown}
          style={{ width: LABEL_W + width }}
        >
          <div role="row" className="flex border-b border-border" style={{ height: HEADER_H }}>
            <div role="columnheader" className="sticky left-0 z-20 shrink-0 border-r border-border bg-surface px-3 py-1.5 text-xs font-medium text-muted" style={{ width: LABEL_W }}>
              {t("schedule.dock")}
            </div>
            <div role="presentation" className="relative" style={{ width }}>
              {hourTicks(axis).map((m) => (
                <span
                  key={m}
                  className="absolute top-1.5 -translate-x-1/2 text-[11px] tabular-nums text-muted"
                  style={{ left: minToPx(m, axis, pxPerHour) }}
                  aria-hidden={m % 120 !== 0 && pxPerHour < 60}
                >
                  {pxPerHour < 60 && m % 120 !== 0 ? "" : formatAxisLabel(m)}
                </span>
              ))}
            </div>
          </div>

          {rows.docks.map(({ dock, placed }, rowIndex) => {
            const lanes = placed[0]?.lanes ?? 1;
            return (
              <div key={dock.id} role="row" aria-rowindex={rowIndex + 2} className="flex border-b border-border last:border-b-0">
                <div role="rowheader" className="sticky left-0 z-10 flex shrink-0 flex-col justify-center gap-1 border-r border-border bg-surface px-3 py-2" style={{ width: LABEL_W }}>
                  <span className="text-sm font-medium">{dock.dock_code}</span>
                  <span className="flex flex-wrap gap-1">
                    <Badge tone={dock.dock_type === "REEFER" ? "accent" : dock.dock_type === "HEAVY" ? "warning" : "neutral"}>
                      {t(`dockType.${dock.dock_type}`)}
                    </Badge>
                    {dock.dock_status !== "ACTIVE" && <Badge tone="danger">{t(`dockStatus.${dock.dock_status}`)}</Badge>}
                  </span>
                </div>
                <div role="presentation" className="relative" style={{ width, height: lanes * LANE_H }}>
                  {hourTicks(axis).map((m) => (
                    <span
                      key={m}
                      aria-hidden="true"
                      className="absolute inset-y-0 w-px bg-border/70"
                      style={{ left: minToPx(m, axis, pxPerHour) }}
                    />
                  ))}
                  {showNow && (
                    <span aria-hidden="true" className="absolute inset-y-0 z-[5] w-0.5 bg-danger" style={{ left: minToPx(nowMin, axis, pxPerHour) }} />
                  )}
                  {placed.map((p) => {
                    const slot = p.item.slot;
                    const style = styleFor(slot.state);
                    const stateLabel = t(`state.${style.labelKey}`);
                    const wide = p.width > 64;
                    const label = `${dock.dock_code} ${hhmm(slot.start, tz)}-${hhmm(slot.end, tz)} ${stateLabel}${
                      slot.appointment ? ` ${slot.appointment.shipment_code}` : ""
                    }`;
                    return (
                      <div
                        key={slot.slot_id}
                        role="gridcell"
                        className="absolute p-px"
                        style={{ left: p.left, width: p.width, top: p.lane * LANE_H, height: LANE_H }}
                      >
                        <button
                          type="button"
                          data-row={rowIndex}
                          data-start={p.item.startMin}
                          aria-label={label}
                          aria-pressed={selectedSlotId === slot.slot_id}
                          onClick={() => onSelect(slot, dock)}
                          onMouseEnter={(e) => show(slot, dock, e.currentTarget)}
                          onMouseLeave={() => setHover(null)}
                          onFocus={(e) => show(slot, dock, e.currentTarget)}
                          onBlur={() => setHover(null)}
                          className={cn(
                            "flex h-full w-full flex-col items-start justify-center overflow-hidden rounded-md px-1.5 text-left transition-shadow",
                            style.className,
                            selectedSlotId === slot.slot_id && "ring-2 ring-ring ring-offset-1",
                          )}
                        >
                          <span className="flex items-center gap-1 font-medium">
                            <span aria-hidden="true">{style.glyph}</span>
                            {wide && <span className="truncate">{slot.appointment?.shipment_code ?? stateLabel}</span>}
                          </span>
                          {wide && <span className="tabular-nums opacity-80">{hhmm(slot.start, tz)}</span>}
                        </button>
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {hover && (
        <div
          role="tooltip"
          className="pointer-events-none fixed z-40 w-72 rounded-lg border border-border bg-surface p-3 text-sm shadow-lg"
          style={{ left: Math.max(8, hover.x), top: hover.y }}
        >
          <p className="font-medium">
            {hover.dock.dock_code} · {hhmm(hover.slot.start, tz)}–{hhmm(hover.slot.end, tz)}
          </p>
          <p className="text-xs text-muted">{t(`state.${styleFor(hover.slot.state).labelKey}`)}</p>
          {hover.slot.appointment && (
            <p className="mt-1 text-xs">
              {hover.slot.appointment.shipment_code} · {hover.slot.appointment.carrier_name ?? "—"}
              {hover.slot.appointment.driver_name ? ` · ${hover.slot.appointment.driver_name}` : ""}
            </p>
          )}
          {hover.slot.event && (
            <p className="mt-1 text-xs">
              {t(`eventType.${hover.slot.event.event_type}`)}: {hover.slot.event.reason}
            </p>
          )}
          {hover.slot.block_reason && <p className="mt-1 text-xs">{hover.slot.block_reason}</p>}
          {hover.slot.history_state && !hover.slot.appointment && (
            <p className="mt-1 text-xs text-muted">{t("schedule.previously", { state: t(`state.${hover.slot.history_state}`) })}</p>
          )}
        </div>
      )}
    </div>
  );
}
