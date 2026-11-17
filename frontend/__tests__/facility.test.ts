import { describe, expect, it } from "vitest";
import { pickFacility } from "../lib/facility-select";
import type { SlotState } from "../lib/facility-types";
import { axisFor, axisWidth, formatAxisLabel, hourTicks, layoutSpans, minToPx } from "../lib/schedule-layout";
import { SLOT_STATES, SLOT_STYLES, isSlotState, styleFor } from "../lib/slot-state";
import { addDays, countdown, hhmm, minutesFromDayStart, todayIn, zonedToIso } from "../lib/time";

describe("schedule axis", () => {
  it("spans the opening hours in whole hours", () => {
    expect(axisFor("06:00", "22:00")).toEqual({ startMin: 360, endMin: 1320 });
    expect(axisFor("06:30", "21:15")).toEqual({ startMin: 360, endMin: 1320 });
  });

  it("widens to include slots outside opening hours", () => {
    expect(axisFor("06:00", "22:00", [{ startMin: 300, endMin: 330 }, { startMin: 1300, endMin: 1500 }])).toEqual({
      startMin: 300,
      endMin: 1500,
    });
  });

  it("never returns an empty axis", () => {
    expect(axisFor("10:00", "10:00")).toEqual({ startMin: 600, endMin: 660 });
  });

  it("converts minutes to pixels and builds hour ticks", () => {
    const axis = { startMin: 360, endMin: 480 };
    expect(minToPx(420, axis, 60)).toBe(60);
    expect(axisWidth(axis, 120)).toBe(240);
    expect(hourTicks(axis)).toEqual([360, 420, 480]);
    expect(formatAxisLabel(1500)).toBe("01:00");
    expect(formatAxisLabel(480)).toBe("08:00");
  });
});

describe("layoutSpans", () => {
  const axis = { startMin: 360, endMin: 1320 }; // 06:00-22:00

  it("places back-to-back slots side by side in one lane", () => {
    const [a, b] = layoutSpans([{ startMin: 480, endMin: 540 }, { startMin: 540, endMin: 600 }], axis, 60);
    expect([a.left, a.width, a.lane]).toEqual([120, 60, 0]);
    expect([b.left, b.width, b.lane]).toEqual([180, 60, 0]);
    expect(a.lanes).toBe(1);
  });

  it("stacks overlapping spans into separate lanes", () => {
    const placed = layoutSpans(
      [{ startMin: 480, endMin: 600 }, { startMin: 540, endMin: 660 }, { startMin: 600, endMin: 660 }],
      axis,
      60,
    );
    expect(placed.map((p) => p.lane)).toEqual([0, 1, 0]);
    expect(placed.every((p) => p.lanes === 2)).toBe(true);
  });

  it("sorts unsorted input by start time", () => {
    const placed = layoutSpans([{ startMin: 600, endMin: 660 }, { startMin: 480, endMin: 540 }], axis, 60);
    expect(placed.map((p) => p.item.startMin)).toEqual([480, 600]);
  });

  it("clips spans that cross the axis edges and flags them", () => {
    const [p] = layoutSpans([{ startMin: 300, endMin: 420 }], axis, 60);
    expect(p.left).toBe(0);
    expect(p.width).toBe(60);
    expect(p.clippedStart).toBe(true);
    expect(p.clippedEnd).toBe(false);
    const [q] = layoutSpans([{ startMin: 1290, endMin: 1400 }], axis, 60);
    expect(q.clippedEnd).toBe(true);
    expect(q.left + q.width).toBe(axisWidth(axis, 60));
  });

  it("drops spans entirely outside the axis, including ones that only touch it", () => {
    const outside = [{ startMin: 0, endMin: 360 }, { startMin: 1320, endMin: 1400 }, { startMin: 100, endMin: 200 }];
    expect(layoutSpans(outside, axis, 60)).toHaveLength(0);
  });

  it("gives zero-length spans a minimum visible width", () => {
    const [p] = layoutSpans([{ startMin: 600, endMin: 600 }], axis, 60);
    expect(p.width).toBeGreaterThan(0);
  });

  it("handles an empty row", () => {
    expect(layoutSpans([], axis, 60)).toEqual([]);
  });

  it("scales with zoom", () => {
    const [a] = layoutSpans([{ startMin: 420, endMin: 510 }], axis, 30);
    const [b] = layoutSpans([{ startMin: 420, endMin: 510 }], axis, 120);
    expect([a.left, a.width]).toEqual([30, 45]);
    expect([b.left, b.width]).toEqual([120, 180]);
  });
});

describe("time helpers", () => {
  it("formats HH:MM in the facility zone", () => {
    expect(hhmm("2026-08-04T08:00:00+05:30")).toBe("08:00");
    expect(hhmm("2026-08-04T02:30:00Z")).toBe("08:00");
    expect(hhmm("2026-08-04T02:30:00Z", "UTC")).toBe("02:30");
    expect(hhmm(null)).toBe("—");
    expect(hhmm("not a date")).toBe("—");
  });

  it("measures minutes from local midnight, across days", () => {
    expect(minutesFromDayStart("2026-08-04T09:15:00+05:30", "2026-08-04")).toBe(555);
    expect(minutesFromDayStart("2026-08-05T01:00:00+05:30", "2026-08-04")).toBe(1500);
    expect(minutesFromDayStart("2026-08-03T23:30:00+05:30", "2026-08-04")).toBe(-30);
  });

  it("finds today's date in a zone", () => {
    const instant = new Date("2026-08-04T20:00:00Z"); // 01:30 next day in IST
    expect(todayIn("Asia/Kolkata", instant)).toBe("2026-08-05");
    expect(todayIn("UTC", instant)).toBe("2026-08-04");
  });

  it("adds days across month boundaries", () => {
    expect(addDays("2026-08-31", 1)).toBe("2026-09-01");
    expect(addDays("2026-03-01", -1)).toBe("2026-02-28");
  });

  it("converts datetime-local input in the facility zone to an instant", () => {
    expect(zonedToIso("2026-08-04T08:00", "Asia/Kolkata")).toBe("2026-08-04T02:30:00.000Z");
    expect(zonedToIso("2026-01-15T12:00", "America/New_York")).toBe("2026-01-15T17:00:00.000Z");
    expect(zonedToIso("2026-07-15T12:00", "America/New_York")).toBe("2026-07-15T16:00:00.000Z");
  });

  it("formats countdowns and clamps at zero", () => {
    const now = Date.parse("2026-08-04T10:00:00Z");
    expect(countdown("2026-08-04T10:05:09Z", now)).toBe("5:09");
    expect(countdown("2026-08-04T09:00:00Z", now)).toBe("0:00");
  });
});

describe("slot state mapping", () => {
  it("covers every slot state with a label key, glyph and colour classes", () => {
    expect(SLOT_STATES).toHaveLength(12);
    for (const s of SLOT_STATES) {
      const style = SLOT_STYLES[s];
      expect(style.labelKey).toBe(s);
      expect(style.glyph.length).toBeGreaterThan(0);
      expect(style.className).toMatch(/bg-/);
    }
  });

  it("uses a distinct glyph per state so colour is never the only cue", () => {
    const glyphs = SLOT_STATES.map((s) => SLOT_STYLES[s].glyph);
    expect(new Set(glyphs).size).toBe(glyphs.length);
  });

  it("gives every coloured state a dark-mode style", () => {
    for (const s of SLOT_STATES.filter((x) => x !== "open")) expect(SLOT_STYLES[s].className).toMatch(/dark:/);
  });

  it("marks booking states as occupying capacity", () => {
    const occupied = SLOT_STATES.filter((s) => SLOT_STYLES[s].occupied);
    expect([...occupied].sort()).toEqual(
      ["completed", "confirmed", "held", "in_progress", "pending_confirmation"] as SlotState[],
    );
  });

  it("falls back to the open style for unknown server values", () => {
    expect(styleFor("something_new")).toBe(SLOT_STYLES.open);
    expect(isSlotState("confirmed")).toBe(true);
    expect(isSlotState("nope")).toBe(false);
  });
});

describe("facility selection", () => {
  const list = [{ id: "a" }, { id: "b" }, { id: "c" }];

  it("prefers the URL, then storage, then the first facility", () => {
    expect(pickFacility(list, "b", "c")).toBe("b");
    expect(pickFacility(list, null, "c")).toBe("c");
    expect(pickFacility(list, null, null)).toBe("a");
  });

  it("ignores ids outside the planner's scope", () => {
    expect(pickFacility(list, "zzz", "yyy")).toBe("a");
    expect(pickFacility([], "a", "b")).toBeNull();
  });
});
