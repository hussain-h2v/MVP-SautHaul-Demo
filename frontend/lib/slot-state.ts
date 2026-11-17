import type { SlotState } from "./facility-types";

export interface SlotStateStyle {
  /** Key in the `facility.state` message namespace. */
  labelKey: SlotState;
  /** Colour classes (light + dark). */
  className: string;
  /** Non-colour cue so state is never conveyed by colour alone. */
  glyph: string;
  /** Whether the block represents a booking that occupies capacity. */
  occupied: boolean;
}

export const SLOT_STATES: SlotState[] = [
  "open",
  "held",
  "pending_confirmation",
  "confirmed",
  "in_progress",
  "completed",
  "cancelled",
  "no_show",
  "blocked",
  "breakdown",
  "maintenance",
  "reduced_capacity",
];

const base = "border text-[11px] leading-tight";

export const SLOT_STYLES: Record<SlotState, SlotStateStyle> = {
  open: {
    labelKey: "open",
    glyph: "○",
    occupied: false,
    className: `${base} border-dashed border-slate-300 bg-surface text-muted hover:bg-accent-soft dark:border-slate-600`,
  },
  held: {
    labelKey: "held",
    glyph: "◔",
    occupied: true,
    className: `${base} border-sky-400 bg-sky-100 text-sky-900 dark:border-sky-500 dark:bg-sky-950 dark:text-sky-100`,
  },
  pending_confirmation: {
    labelKey: "pending_confirmation",
    glyph: "◐",
    occupied: true,
    className: `${base} border-amber-500 bg-amber-100 text-amber-900 dark:border-amber-500 dark:bg-amber-950 dark:text-amber-100`,
  },
  confirmed: {
    labelKey: "confirmed",
    glyph: "●",
    occupied: true,
    className: `${base} border-indigo-500 bg-indigo-100 text-indigo-900 dark:border-indigo-400 dark:bg-indigo-950 dark:text-indigo-100`,
  },
  in_progress: {
    labelKey: "in_progress",
    glyph: "▶",
    occupied: true,
    className: `${base} border-emerald-600 bg-emerald-200 text-emerald-950 dark:border-emerald-500 dark:bg-emerald-900 dark:text-emerald-50`,
  },
  completed: {
    labelKey: "completed",
    glyph: "✓",
    occupied: true,
    className: `${base} border-emerald-400 bg-emerald-50 text-emerald-900 dark:border-emerald-700 dark:bg-emerald-950 dark:text-emerald-200`,
  },
  cancelled: {
    labelKey: "cancelled",
    glyph: "✕",
    occupied: false,
    className: `${base} border-slate-400 bg-slate-100 text-slate-500 line-through dark:border-slate-600 dark:bg-slate-800 dark:text-slate-400`,
  },
  no_show: {
    labelKey: "no_show",
    glyph: "⊘",
    occupied: false,
    className: `${base} border-rose-400 bg-rose-50 text-rose-800 dark:border-rose-600 dark:bg-rose-950 dark:text-rose-200`,
  },
  blocked: {
    labelKey: "blocked",
    glyph: "▬",
    occupied: false,
    className: `${base} border-slate-500 bg-slate-300 text-slate-800 dark:border-slate-500 dark:bg-slate-700 dark:text-slate-100`,
  },
  breakdown: {
    labelKey: "breakdown",
    glyph: "⚠",
    occupied: false,
    className: `${base} border-red-600 bg-red-200 text-red-900 dark:border-red-500 dark:bg-red-950 dark:text-red-100`,
  },
  maintenance: {
    labelKey: "maintenance",
    glyph: "⚙",
    occupied: false,
    className: `${base} border-orange-500 bg-orange-100 text-orange-900 dark:border-orange-500 dark:bg-orange-950 dark:text-orange-100`,
  },
  reduced_capacity: {
    labelKey: "reduced_capacity",
    glyph: "↓",
    occupied: false,
    className: `${base} border-yellow-500 bg-yellow-100 text-yellow-900 dark:border-yellow-500 dark:bg-yellow-950 dark:text-yellow-100`,
  },
};

/** Style for a server-provided state; unknown values degrade to "open" rather than crashing the grid. */
export function styleFor(state: string): SlotStateStyle {
  return SLOT_STYLES[state as SlotState] ?? SLOT_STYLES.open;
}

export function isSlotState(v: string): v is SlotState {
  return v in SLOT_STYLES;
}
