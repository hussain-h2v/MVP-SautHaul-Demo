import { describe, expect, it } from "vitest";
import en from "../messages/en.json";
import hi from "../messages/hi.json";
import { ApiError } from "../lib/api";
import type { ScheduleSlot } from "../lib/facility-types";
import {
  classifyMove, isDropTarget, isFixed, isMovable, slotMinutes, slotsNeeded, targetRun, VERDICT_RING,
} from "../lib/move";
import { describeMoveError, describeProblem, MOVE_ERROR_CODES, PROBLEM_CODES, problemMessage, type Tr } from "../lib/problems";

function slot(id: string, startH: number, state: ScheduleSlot["state"] = "open", withAppt = false): ScheduleSlot {
  const pad = (n: number) => String(n).padStart(2, "0");
  return {
    slot_id: id,
    code: id,
    start: `2026-08-04T${pad(startH)}:00:00Z`,
    end: `2026-08-04T${pad(startH + 1)}:00:00Z`,
    state,
    block_reason: null,
    history_state: null,
    event: null,
    appointment: withAppt
      ? { id: "A1", code: "APT1", status: state === "pending_confirmation" ? "PENDING_CONFIRMATION" : "CONFIRMED", shipment_code: "SHP1", carrier_name: null, driver_name: null, priority_code: "HIGH" }
      : null,
  };
}

describe("classifyMove (validate-move response -> target colour)", () => {
  it("is feasible (green) when the server says feasible with no approval", () => {
    expect(classifyMove({ feasible: true, problems: [], needs_planner_approval: false }, false)).toBe("feasible");
  });
  it("is amber when feasible but the planner must approve", () => {
    expect(classifyMove({ feasible: true, problems: [], needs_planner_approval: true }, false)).toBe("approval");
  });
  it("is red when infeasible, even if approval would be needed", () => {
    expect(classifyMove({ feasible: false, problems: ["DOCK_EVENT"], needs_planner_approval: true }, false)).toBe("infeasible");
  });
  it("is 'checking' while the request is in flight or missing", () => {
    expect(classifyMove(undefined, true)).toBe("checking");
    expect(classifyMove(null, false)).toBe("checking");
    expect(classifyMove({ feasible: true, problems: [], needs_planner_approval: false }, true)).toBe("checking");
  });
  it("has a distinct ring style per verdict", () => {
    expect(new Set(Object.values(VERDICT_RING)).size).toBe(4);
  });
});

describe("move eligibility", () => {
  it("only confirmed or pending bookings with an appointment are movable", () => {
    expect(isMovable(slot("a", 8, "confirmed", true))).toBe(true);
    expect(isMovable(slot("a", 8, "pending_confirmation", true))).toBe(true);
    expect(isMovable(slot("a", 8, "confirmed", false))).toBe(false);
    expect(isMovable(slot("a", 8, "open"))).toBe(false);
    expect(isMovable(slot("a", 8, "held", true))).toBe(false);
  });
  it("trucks already unloading or done are fixed", () => {
    expect(isFixed(slot("a", 8, "in_progress", true))).toBe(true);
    expect(isFixed(slot("a", 8, "completed", true))).toBe(true);
    expect(isFixed(slot("a", 8, "confirmed", true))).toBe(false);
  });
  it("drop targets are open slots other than the source", () => {
    expect(isDropTarget(slot("b", 9), "a")).toBe(true);
    expect(isDropTarget(slot("a", 9), "a")).toBe(false);
    expect(isDropTarget(slot("b", 9, "blocked"), "a")).toBe(false);
  });
});

describe("multi-window targets", () => {
  it("computes the number of back-to-back slots a load needs", () => {
    expect(slotsNeeded(60, 60)).toBe(1);
    expect(slotsNeeded(90, 60)).toBe(2);
    expect(slotsNeeded(181, 90)).toBe(3);
    expect(slotsNeeded(undefined, 60)).toBe(1);
    expect(slotMinutes(slot("a", 8))).toBe(60);
  });
  it("collects consecutive slots and stops at a gap or the end of the day", () => {
    const dock = { slots: [slot("a", 8), slot("b", 9), slot("c", 11), slot("d", 12)] };
    expect(targetRun(dock, "a", 2).map((s) => s.slot_id)).toEqual(["a", "b"]);
    expect(targetRun(dock, "b", 3).map((s) => s.slot_id)).toEqual(["b"]);
    expect(targetRun(dock, "c", 3).map((s) => s.slot_id)).toEqual(["c", "d"]);
    expect(targetRun(dock, "zzz", 2)).toEqual([]);
  });
});

type Messages = typeof en;
const lookup = (m: Messages, key: string): string | undefined =>
  key.split(".").reduce<unknown>((o, k) => (o as Record<string, unknown> | undefined)?.[k], m.facility) as string | undefined;

describe("problem and error code strings", () => {
  it("every code has a non-empty en and hi string, and hi is translated", () => {
    for (const code of PROBLEM_CODES) {
      const { key } = problemMessage(code);
      const e = lookup(en, key);
      const h = lookup(hi as unknown as Messages, key);
      expect(e, `en ${key}`).toBeTruthy();
      expect(h, `hi ${key}`).toBeTruthy();
      expect(h).not.toBe(e);
    }
    for (const code of MOVE_ERROR_CODES) {
      expect(lookup(en, `moveErrors.${code}`), code).toBeTruthy();
      expect(lookup(hi as unknown as Messages, `moveErrors.${code}`), code).toBeTruthy();
    }
  });

  it("maps COMBINES_n_WINDOWS to the parameterised message", () => {
    expect(problemMessage("COMBINES_3_WINDOWS")).toEqual({ key: "problems.COMBINES_N_WINDOWS", values: { n: 3 } });
  });

  const t: Tr = (key, values) => `${key}${values ? JSON.stringify(values) : ""}`;

  it("describes known codes and falls back to the raw code for unknown ones", () => {
    expect(describeProblem("OCCUPIED", t)).toBe("problems.OCCUPIED");
    expect(describeProblem("COMBINES_2_WINDOWS", t)).toBe('problems.COMBINES_N_WINDOWS{"n":2}');
    expect(describeProblem("SOMETHING_NEW", t)).toBe("SOMETHING_NEW");
  });

  it("turns 409 move errors into messages, listing SLOT_UNAVAILABLE reasons", () => {
    expect(describeMoveError(new ApiError(409, "SLOT_TAKEN", "x"), t)).toBe("moveErrors.SLOT_TAKEN");
    expect(describeMoveError(new ApiError(409, "FIXED_IN_PROGRESS", "x"), t)).toBe("moveErrors.FIXED_IN_PROGRESS");
    const u = describeMoveError(new ApiError(409, "SLOT_UNAVAILABLE", "x", { reasons: ["DOCK_EVENT", "BEFORE_ETA"] }), t);
    expect(u).toContain("moveErrors.SLOT_UNAVAILABLE");
    expect(u).toContain("problems.DOCK_EVENT");
    expect(u).toContain("problems.BEFORE_ETA");
    expect(describeMoveError(new Error("boom"), t)).toBe("moveErrors.generic");
    expect(describeMoveError(new ApiError(500, "INTERNAL", "Server broke"), t)).toBe("Server broke");
  });
});
