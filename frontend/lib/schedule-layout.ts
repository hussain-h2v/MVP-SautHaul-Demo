import { parseHHMM } from "./time";

export interface Axis {
  startMin: number;
  endMin: number;
}

export interface Span {
  startMin: number;
  endMin: number;
}

export interface Placed<T> {
  item: T;
  left: number;
  width: number;
  lane: number;
  lanes: number;
  /** true when the slot starts before / ends after the visible axis. */
  clippedStart: boolean;
  clippedEnd: boolean;
}

export const MIN_BLOCK_PX = 6;
export const ZOOM_LEVELS = [30, 60, 120] as const;

/** Visible axis: facility opening hours widened (to whole hours) so no slot is cut off. */
export function axisFor(open: string, close: string, spans: Span[] = []): Axis {
  let start = parseHHMM(open);
  let end = parseHHMM(close);
  for (const s of spans) {
    start = Math.min(start, s.startMin);
    end = Math.max(end, s.endMin);
  }
  start = Math.floor(start / 60) * 60;
  end = Math.ceil(end / 60) * 60;
  if (end <= start) end = start + 60;
  return { startMin: start, endMin: end };
}

export function axisWidth(axis: Axis, pxPerHour: number): number {
  return ((axis.endMin - axis.startMin) / 60) * pxPerHour;
}

export function hourTicks(axis: Axis): number[] {
  const ticks: number[] = [];
  for (let m = axis.startMin; m <= axis.endMin; m += 60) ticks.push(m);
  return ticks;
}

export function minToPx(min: number, axis: Axis, pxPerHour: number): number {
  return ((min - axis.startMin) / 60) * pxPerHour;
}

/**
 * Places spans on one dock row. Spans that overlap in time (not expected for slots on one dock,
 * but defended against) get separate lanes. Spans entirely outside the axis are dropped; spans
 * partly outside are clipped to it.
 */
export function layoutSpans<T extends Span>(items: T[], axis: Axis, pxPerHour: number): Placed<T>[] {
  const visible = items
    .filter((i) => i.endMin > axis.startMin && i.startMin < axis.endMin)
    .sort((a, b) => a.startMin - b.startMin || a.endMin - b.endMin);
  const laneEnds: number[] = [];
  const placed = visible.map((item) => {
    let lane = laneEnds.findIndex((end) => end <= item.startMin);
    if (lane === -1) {
      lane = laneEnds.length;
      laneEnds.push(item.endMin);
    } else laneEnds[lane] = item.endMin;
    const s = Math.max(item.startMin, axis.startMin);
    const e = Math.min(item.endMin, axis.endMin);
    return {
      item,
      left: minToPx(s, axis, pxPerHour),
      width: Math.max(((e - s) / 60) * pxPerHour, MIN_BLOCK_PX),
      lane,
      lanes: 1,
      clippedStart: item.startMin < axis.startMin,
      clippedEnd: item.endMin > axis.endMin,
    };
  });
  const lanes = Math.max(1, laneEnds.length);
  return placed.map((p) => ({ ...p, lanes }));
}

export function formatAxisLabel(min: number): string {
  const m = ((min % 1440) + 1440) % 1440;
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}
