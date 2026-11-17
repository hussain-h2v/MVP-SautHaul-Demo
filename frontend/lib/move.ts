import type { ScheduleDock, ScheduleSlot } from "./facility-types";

export interface MoveCheck {
  feasible: boolean;
  problems: string[];
  needs_planner_approval: boolean;
}

export type MoveVerdict = "checking" | "feasible" | "approval" | "infeasible";

/** Colour class family for a drop target, from the validate-move response. */
export function classifyMove(check: MoveCheck | undefined | null, pending: boolean): MoveVerdict {
  if (pending || !check) return "checking";
  if (!check.feasible) return "infeasible";
  return check.needs_planner_approval ? "approval" : "feasible";
}

export const VERDICT_RING: Record<MoveVerdict, string> = {
  checking: "ring-2 ring-slate-400 ring-offset-1",
  feasible: "ring-2 ring-emerald-500 ring-offset-1 bg-emerald-50 dark:bg-emerald-950",
  approval: "ring-2 ring-amber-500 ring-offset-1 bg-amber-50 dark:bg-amber-950",
  infeasible: "ring-2 ring-red-500 ring-offset-1 bg-red-50 dark:bg-red-950",
};

export const MOVABLE_STATES = ["confirmed", "pending_confirmation"] as const;

export function isMovable(slot: ScheduleSlot): boolean {
  return (MOVABLE_STATES as readonly string[]).includes(slot.state) && !!slot.appointment && slot.appointment.status !== "HELD";
}

export function isFixed(slot: ScheduleSlot): boolean {
  return slot.state === "in_progress" || slot.state === "completed";
}

export function slotMinutes(slot: Pick<ScheduleSlot, "start" | "end">): number {
  return Math.round((new Date(slot.end).getTime() - new Date(slot.start).getTime()) / 60_000);
}

/** How many back-to-back slots a load of `unloadMin` needs when slots are `slotMin` long (at least one). */
export function slotsNeeded(unloadMin: number | null | undefined, slotMin: number): number {
  if (!unloadMin || unloadMin <= 0 || slotMin <= 0) return 1;
  return Math.max(1, Math.ceil(unloadMin / slotMin));
}

/**
 * The run of consecutive slots on a dock starting at `startSlotId`. Returns the slots found, which may be fewer
 * than `count` when the dock has a gap or the day ends; the server then reports TOO_SHORT / NOT_CONSECUTIVE.
 */
export function targetRun(dock: Pick<ScheduleDock, "slots">, startSlotId: string, count: number): ScheduleSlot[] {
  const ordered = [...dock.slots].sort((a, b) => a.start.localeCompare(b.start));
  const i = ordered.findIndex((s) => s.slot_id === startSlotId);
  if (i < 0) return [];
  const run = [ordered[i]];
  while (run.length < count && i + run.length < ordered.length) {
    const next = ordered[i + run.length];
    if (next.start !== run[run.length - 1].end) break;
    run.push(next);
  }
  return run;
}

/** A drop target must be open and not the booking's own slot. */
export function isDropTarget(slot: ScheduleSlot, sourceSlotId: string): boolean {
  return slot.state === "open" && slot.slot_id !== sourceSlotId;
}
