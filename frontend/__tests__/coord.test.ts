import { describe, expect, it } from "vitest";
import en from "../messages/en.json";
import hi from "../messages/hi.json";
import {
  countdownTone,
  inboxHref,
  languageName,
  MIN_OVERRIDE_REASON,
  nextIndex,
  secondsLeft,
  sortInbox,
  validateCompetingDecision,
} from "../lib/coord";
import { filterNav, portals } from "../lib/portals";
import type { UserOut } from "../lib/types";

const item = (priority_code: string | null, created_at: string, id = created_at + priority_code) => ({ id, priority_code, created_at });

describe("sortInbox", () => {
  it("puts CRITICAL first, then HIGH/NORMAL/LOW", () => {
    const sorted = sortInbox([
      item("LOW", "2026-08-04T08:00:00Z"),
      item("NORMAL", "2026-08-04T08:00:00Z"),
      item("CRITICAL", "2026-08-04T09:00:00Z"),
      item("HIGH", "2026-08-04T07:00:00Z"),
    ]);
    expect(sorted.map((x) => x.priority_code)).toEqual(["CRITICAL", "HIGH", "NORMAL", "LOW"]);
  });

  it("orders the same priority oldest first", () => {
    const sorted = sortInbox([item("HIGH", "2026-08-04T10:00:00Z"), item("HIGH", "2026-08-04T08:00:00Z"), item("HIGH", "2026-08-04T09:00:00Z")]);
    expect(sorted.map((x) => x.created_at)).toEqual(["2026-08-04T08:00:00Z", "2026-08-04T09:00:00Z", "2026-08-04T10:00:00Z"]);
  });

  it("treats a missing or unknown priority as lowest and is stable for ties", () => {
    const a = item(null, "2026-08-04T08:00:00Z", "a");
    const b = item("WEIRD", "2026-08-04T08:00:00Z", "b");
    const c = item("LOW", "2026-08-04T08:00:00Z", "c");
    expect(sortInbox([a, b, c]).map((x) => x.id)).toEqual(["c", "a", "b"]);
  });

  it("does not mutate its input", () => {
    const input = [item("LOW", "2026-08-04T08:00:00Z"), item("CRITICAL", "2026-08-04T08:00:00Z")];
    sortInbox(input);
    expect(input[0].priority_code).toBe("LOW");
  });
});

describe("countdownTone", () => {
  it("is ok above 5 minutes, amber under 5, red under 1, expired at zero", () => {
    expect(countdownTone(900)).toBe("ok");
    expect(countdownTone(300)).toBe("ok");
    expect(countdownTone(299)).toBe("warn");
    expect(countdownTone(60)).toBe("warn");
    expect(countdownTone(59)).toBe("danger");
    expect(countdownTone(1)).toBe("danger");
    expect(countdownTone(0)).toBe("expired");
    expect(countdownTone(-30)).toBe("expired");
  });

  it("computes seconds left from an expiry instant", () => {
    const now = Date.parse("2026-08-04T10:00:00Z");
    expect(secondsLeft("2026-08-04T10:04:30Z", now)).toBe(270);
    expect(secondsLeft("2026-08-04T09:59:00Z", now)).toBe(-60);
  });
});

describe("validateCompetingDecision", () => {
  it("accepts the policy winner without a reason", () => {
    expect(validateCompetingDecision({ winnerId: "r1", policyWinnerId: "r1", reason: "" })).toEqual({ ok: true, overrode: false });
  });

  it("requires a written reason of at least 10 characters to override", () => {
    expect(validateCompetingDecision({ winnerId: "r2", policyWinnerId: "r1", reason: "" })).toEqual({ ok: false, error: "reasonRequired" });
    expect(validateCompetingDecision({ winnerId: "r2", policyWinnerId: "r1", reason: "too short" })).toEqual({ ok: false, error: "reasonRequired" });
    expect(validateCompetingDecision({ winnerId: "r2", policyWinnerId: "r1", reason: "   padded   " })).toEqual({ ok: false, error: "reasonRequired" });
    expect(validateCompetingDecision({ winnerId: "r2", policyWinnerId: "r1", reason: "x".repeat(MIN_OVERRIDE_REASON) })).toEqual({ ok: true, overrode: true });
  });

  it("needs a winner", () => {
    expect(validateCompetingDecision({ winnerId: null, policyWinnerId: "r1", reason: "irrelevant reason text" })).toEqual({ ok: false, error: "noWinner" });
  });
});

describe("inboxHref and keyboard navigation", () => {
  it("routes each kind to its screen", () => {
    expect(inboxHref({ kind: "request", id: "r1", shipment_code: "SHP1" })).toBe("/coordinator/requests/r1");
    expect(inboxHref({ kind: "escalation", id: "e1", shipment_code: null })).toBe("/coordinator/escalations/e1");
    expect(inboxHref({ kind: "hold", id: "h1", shipment_code: "SHP1" })).toBe("/coordinator/holds");
    expect(inboxHref({ kind: "exception", id: "x", shipment_code: "SHP 1" })).toBe("/coordinator/conversations?q=SHP%201");
    expect(inboxHref({ kind: "failed_message", id: "m", shipment_code: null })).toBe("/coordinator/conversations");
    expect(inboxHref({ kind: "eta_change", id: "t", shipment_code: "SHP1" })).toBe("/coordinator/board");
  });

  it("moves the selection with j/k and clamps at the ends", () => {
    expect(nextIndex(-1, 1, 3)).toBe(0);
    expect(nextIndex(-1, -1, 3)).toBe(2);
    expect(nextIndex(0, -1, 3)).toBe(0);
    expect(nextIndex(2, 1, 3)).toBe(2);
    expect(nextIndex(1, 1, 3)).toBe(2);
    expect(nextIndex(0, 1, 0)).toBe(-1);
  });

  it("shows a driver language by its native name", () => {
    expect(languageName("hi")).toContain("Hindi");
    expect(languageName("xx")).toBe("xx");
    expect(languageName(null)).toBe("—");
  });
});

describe("coordinator navigation and messages", () => {
  const user = (caps: UserOut["capabilities"]) => ({ capabilities: caps });
  const portal = portals.find((p) => p.slug === "coordinator")!;

  it("shows every coordinator screen to a coordinator", () => {
    const full = user({ booking_decisions: "W", escalations_takeover: "W", day_schedule: "R", ai_insights: "W", audit_log: "R" });
    expect(filterNav(portal.nav, full).map((n) => n.href)).toEqual([
      "/coordinator",
      "/coordinator/competing",
      "/coordinator/holds",
      "/coordinator/escalations",
      "/coordinator/conversations",
      "/coordinator/board",
      "/coordinator/handover",
      "/coordinator/insights",
      "/coordinator/activity",
      "/coordinator/notifications",
    ]);
  });

  it("hides decision screens from someone without the capability", () => {
    const hrefs = filterNav(portal.nav, user({ day_schedule: "R" })).map((n) => n.href);
    expect(hrefs).toEqual(["/coordinator/board", "/coordinator/notifications"]);
  });

  it("has Hindi for every English coordinator string", () => {
    const keys = (o: Record<string, unknown>, p = ""): string[] =>
      Object.entries(o).flatMap(([k, v]) => (typeof v === "object" && v !== null ? keys(v as Record<string, unknown>, `${p}${k}.`) : [`${p}${k}`]));
    expect(keys(hi.coord)).toEqual(keys(en.coord));
    for (const k of ["competing", "conversations", "handover", "activity"]) expect(hi.nav).toHaveProperty(k);
  });

  it("names every status the badge can show", () => {
    for (const s of ["waiting", "held", "suggested", "approved", "rejected", "expired", "escalated", "open", "in_progress", "resolved"]) {
      expect(en.coord.status).toHaveProperty(s);
    }
  });
});
