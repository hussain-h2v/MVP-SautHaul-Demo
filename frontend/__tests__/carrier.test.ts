import { describe, expect, it } from "vitest";
import en from "../messages/en.json";
import hi from "../messages/hi.json";
import {
  ASSIGN_CODES,
  ASSIGN_PROBLEM_CODES,
  ASSIGN_WARNING_CODES,
  assignmentMessage,
  badgeCount,
  canSubmitAssignment,
  groupByDay,
  languageLabel,
  LANGUAGE_OPTIONS,
  NOTIFICATION_TYPES,
  notificationsHref,
  notificationTypeKey,
  pickParams,
  SLOT_CHANGE_KINDS,
  slotChangeTone,
  toCsvFilename,
  type Tr,
} from "../lib/carrier";

type Dict = Record<string, unknown>;

function lookup(root: Dict, path: string): unknown {
  return path.split(".").reduce<unknown>((o, k) => (o && typeof o === "object" ? (o as Dict)[k] : undefined), root);
}

/** Minimal next-intl-like translator over a message tree, scoped to the "carrier" namespace. */
function tr(messages: Dict): Tr {
  const t = ((key: string) => String(lookup(messages, `carrier.${key}`) ?? key)) as Tr;
  t.has = (key: string) => typeof lookup(messages, `carrier.${key}`) === "string";
  return t;
}

function keys(o: Dict, prefix = ""): string[] {
  return Object.entries(o).flatMap(([k, v]) => (v && typeof v === "object" ? keys(v as Dict, `${prefix}${k}.`) : [`${prefix}${k}`]));
}

describe("assignment message mapping", () => {
  it("has an English and a Hindi message for every problem and warning code", () => {
    for (const code of ASSIGN_CODES) {
      expect(lookup(en, `carrier.assign.codes.${code}`), `en ${code}`).toBeTypeOf("string");
      expect(lookup(hi, `carrier.assign.codes.${code}`), `hi ${code}`).toBeTypeOf("string");
    }
  });

  it("splits blocking problems from warnings with no overlap", () => {
    expect(ASSIGN_PROBLEM_CODES.length).toBe(6);
    expect(ASSIGN_WARNING_CODES).toEqual(["DRIVER_ON_ANOTHER_SHIPMENT", "DRIVER_NOT_VERIFIED"]);
    expect(new Set(ASSIGN_CODES).size).toBe(ASSIGN_CODES.length);
  });

  it("prefers our translation and falls back to the server message for unknown codes", () => {
    const t = tr(en as Dict);
    expect(assignmentMessage(t, { code: "VEHICLE_NOT_REFRIGERATED", message: "server text" })).toBe("This load needs a refrigerated vehicle.");
    expect(assignmentMessage(t, { code: "SOMETHING_NEW", message: "Server says no" })).toBe("Server says no");
    expect(assignmentMessage(t, { code: "SOMETHING_NEW", message: "" })).toBe("SOMETHING_NEW");
    expect(assignmentMessage(tr(hi as Dict), { code: "DRIVER_INACTIVE", message: "x" })).toBe("यह ड्राइवर सक्रिय नहीं है।");
  });

  it("only lets the form submit when both are chosen and the check has no blocking problem", () => {
    const ok = { problems: [] };
    const bad = { problems: [{ code: "LOAD_EXCEEDS_CAPACITY", message: "" }] };
    expect(canSubmitAssignment("d", "v", ok)).toBe(true);
    expect(canSubmitAssignment("d", "v", bad)).toBe(false);
    expect(canSubmitAssignment("", "v", ok)).toBe(false);
    expect(canSubmitAssignment("d", "", ok)).toBe(false);
    expect(canSubmitAssignment("d", "v", undefined)).toBe(false);
    expect(canSubmitAssignment("d", "v", null)).toBe(false);
  });
});

describe("driver languages", () => {
  it("offers the nine bot languages with native names, English first", () => {
    expect(LANGUAGE_OPTIONS.map((l) => l.code)).toEqual(["en", "hi", "te", "mr", "gu", "pa", "ta", "kn", "bn"]);
    expect(LANGUAGE_OPTIONS[1].native).toBe("हिन्दी");
    expect(new Set(LANGUAGE_OPTIONS.map((l) => l.native)).size).toBe(9);
  });

  it("labels codes, tolerating case and unknown values", () => {
    expect(languageLabel("hi")).toBe("हिन्दी (HI)");
    expect(languageLabel("TE")).toBe("తెలుగు (TE)");
    expect(languageLabel("xx")).toBe("XX");
    expect(languageLabel(null)).toBe("—");
  });
});

describe("notification grouping and badge", () => {
  it("groups by India calendar day, newest day first, keeping order inside a day", () => {
    const items = [
      { id: "a", ts: "2026-08-04T10:00:00Z" },
      { id: "b", ts: "2026-08-03T10:00:00Z" },
      { id: "c", ts: "2026-08-04T02:00:00Z" },
    ];
    const g = groupByDay(items, (i) => i.ts);
    expect(g.map((x) => x.day)).toEqual(["2026-08-04", "2026-08-03"]);
    expect(g[0].items.map((i) => i.id)).toEqual(["a", "c"]);
  });

  it("uses Asia/Kolkata, not UTC, to decide the day", () => {
    // 20:00Z on the 3rd is 01:30 IST on the 4th
    const g = groupByDay([{ ts: "2026-08-03T20:00:00Z" }, { ts: "2026-08-03T10:00:00Z" }], (i) => i.ts);
    expect(g.map((x) => x.day)).toEqual(["2026-08-04", "2026-08-03"]);
  });

  it("handles empty input and invalid timestamps", () => {
    expect(groupByDay([], () => "")).toEqual([]);
    expect(groupByDay([{ ts: "not a date" }], (i) => i.ts)[0].day).toBe("unknown");
  });

  it("caps the badge at 99+ and hides it at zero", () => {
    expect(badgeCount(0)).toBe("");
    expect(badgeCount(-3)).toBe("");
    expect(badgeCount(7)).toBe("7");
    expect(badgeCount(99)).toBe("99");
    expect(badgeCount(100)).toBe("99+");
  });

  it("maps dotted notification types to snake_case message keys", () => {
    expect(notificationTypeKey("shipment.offered")).toBe("shipment_offered");
    expect(notificationTypeKey("escalation.created")).toBe("escalation_created");
    expect(notificationTypeKey("plain")).toBe("plain");
  });

  it("links 'view all' to each portal's own notifications page", () => {
    for (const slug of ["admin", "facility", "coordinator", "carrier"]) expect(notificationsHref(slug)).toBe(`/${slug}/notifications`);
  });

  it("has a label in both languages for every notification type", () => {
    for (const type of NOTIFICATION_TYPES) {
      expect(lookup(en, `notifications.types.${notificationTypeKey(type)}`), `en ${type}`).toBeTypeOf("string");
      expect(lookup(hi, `notifications.types.${notificationTypeKey(type)}`), `hi ${type}`).toBeTypeOf("string");
    }
  });
});

describe("slot-change feed", () => {
  it("has labels in both languages and a tone for every kind", () => {
    for (const k of SLOT_CHANGE_KINDS) {
      expect(lookup(en, `carrier.slotChanges.kinds.${k}`)).toBeTypeOf("string");
      expect(lookup(hi, `carrier.slotChanges.kinds.${k}`)).toBeTypeOf("string");
      expect(["neutral", "accent", "success", "warning", "danger"]).toContain(slotChangeTone(k));
    }
    expect(slotChangeTone("confirmed")).toBe("success");
    expect(slotChangeTone("rejected")).toBe("danger");
    expect(slotChangeTone("suggested")).toBe("warning");
    expect(slotChangeTone("replaced")).toBe("neutral");
  });
});

describe("url params and filenames", () => {
  it("keeps only known, non-empty params", () => {
    expect(pickParams("?verified=false&x=1&language=", ["verified", "language"])).toEqual({ verified: "false" });
    expect(pickParams("", ["verified"])).toEqual({});
  });

  it("names report files by kind and range", () => {
    expect(toCsvFilename("delays", "2026-08-01", "2026-08-31")).toBe("carrier-delays-2026-08-01-2026-08-31.csv");
  });
});

describe("message completeness", () => {
  it("English and Hindi carrier and notification trees have identical keys", () => {
    for (const ns of ["carrier", "notifications"]) {
      const a = keys((en as Dict)[ns] as Dict).sort();
      const b = keys((hi as Dict)[ns] as Dict).sort();
      expect(b, ns).toEqual(a);
    }
  });

  it("has no empty strings in the new namespaces", () => {
    for (const messages of [en, hi] as Dict[]) {
      for (const ns of ["carrier", "notifications"]) {
        for (const key of keys(messages[ns] as Dict)) expect(String(lookup(messages[ns] as Dict, key)).length, `${ns}.${key}`).toBeGreaterThan(0);
      }
    }
  });
});
