import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  bodyVariables, catalogueLanguages, deliveryTicks, detectLanguageHint, pendingBubble, QUICK_TESTS, quickReplyPayload, renderPreview,
  textPayload, toBubble, toBubbles, validateButtons, validateTemplateVars,
} from "../lib/wa";
import type { SimMessage } from "../lib/wa-types";
import en from "../messages/en.json";
import hi from "../messages/hi.json";

describe("template variable validation", () => {
  it("finds unique placeholders with or without spaces", () => {
    expect(bodyVariables("Slot {{slot_code}} at {{ start }}, dock {{dock_code}} {{slot_code}}")).toEqual(["slot_code", "start", "dock_code"]);
    expect(bodyVariables("no variables")).toEqual([]);
  });
  it("accepts a body that uses exactly the declared variables", () => {
    expect(validateTemplateVars("Dock {{dock_code}} from {{start}}", ["dock_code", "start"])).toEqual({ ok: true, unused: [], unknown: [] });
  });
  it("reports declared-but-unused and used-but-undeclared variables", () => {
    const r = validateTemplateVars("Dock {{dock_code}} {{surprise}}", ["dock_code", "start"]);
    expect(r.ok).toBe(false);
    expect(r.unused).toEqual(["start"]);
    expect(r.unknown).toEqual(["surprise"]);
  });
  it("previews with sample values and shows unknown names in angle brackets", () => {
    expect(renderPreview("Dock {{dock_code}} for {{who}}")).toBe("Dock D3 for <who>");
    expect(renderPreview("{{ code }}", { code: "9" })).toBe("9");
  });
});

describe("quick-reply buttons", () => {
  it("allows up to three labelled, unique buttons of at most 20 characters", () => {
    expect(validateButtons([{ id: "a", title: "Accept" }, { id: "b", title: "Decline" }])).toBeNull();
    expect(validateButtons([1, 2, 3, 4].map((n) => ({ id: `b${n}`, title: `B${n}` })))).toBe("tooMany");
    expect(validateButtons([{ id: "", title: "x" }])).toBe("empty");
    expect(validateButtons([{ id: "a", title: "x".repeat(21) }])).toBe("tooLong");
    expect(validateButtons([{ id: "a", title: "x" }, { id: "a", title: "y" }])).toBe("duplicate");
  });
  it("lists en, hi and te first, then any others sorted", () => {
    expect(catalogueLanguages(["ta", "en", "hi", "bn", "te", "ta"])).toEqual(["en", "hi", "te", "bn", "ta"]);
    expect(catalogueLanguages([])).toEqual(["en", "hi", "te"]);
  });
});

const msg = (over: Partial<SimMessage>): SimMessage => ({
  id: "m", direction: "out", kind: "text", text: "hi", buttons: [], rows: [], language: "en", purpose: null, template_name: null,
  delivery_status: "sent", created_at: "2026-12-01T05:00:00Z", ...over,
});

describe("message to bubble mapping", () => {
  it("puts the driver on the right and the bot on the left", () => {
    expect(toBubble(msg({ direction: "in" })).side).toBe("driver");
    expect(toBubble(msg({ direction: "out" })).side).toBe("bot");
  });
  it("never shows tap targets on driver messages", () => {
    const b = toBubble(msg({ direction: "in", buttons: [{ id: "x", title: "X" }] }), true);
    expect(b.buttons).toEqual([]);
    expect(b.tappable).toBe(false);
  });
  it("makes only the newest bot message with options tappable", () => {
    const list = [
      msg({ id: "1", buttons: [{ id: "a", title: "A" }] }),
      msg({ id: "2", direction: "in", text: "A" }),
      msg({ id: "3", rows: [{ id: "r1", title: "Option 1", description: "10:00" }] }),
      msg({ id: "4", direction: "in", text: "Option 1" }),
    ];
    const bubbles = toBubbles(list);
    expect(bubbles.map((b) => b.tappable)).toEqual([false, false, true, false]);
    expect(bubbles[2].rows[0].title).toBe("Option 1");
  });
  it("names a text-less template message and keeps the template", () => {
    const b = toBubble(msg({ kind: "template", text: null, template_name: "appointment_confirmed" }));
    expect(b.text).toBe("[appointment_confirmed]");
    expect(b.template).toBe("appointment_confirmed");
  });
  it("marks the optimistic driver bubble as pending", () => {
    const p = pendingBubble("hello", new Date("2026-12-01T05:00:00Z"));
    expect(p).toMatchObject({ side: "driver", text: "hello", status: "pending" });
  });
  it("maps delivery status to ticks", () => {
    expect(deliveryTicks("pending").ticks).toBe(0);
    expect(deliveryTicks("sent").ticks).toBe(1);
    expect(deliveryTicks("delivered")).toEqual({ ticks: 2, read: false });
    expect(deliveryTicks("read")).toEqual({ ticks: 2, read: true });
    expect(deliveryTicks("failed").ticks).toBe(0);
  });
});

describe("quick-reply payload builder", () => {
  it("sends the id and visible title exactly like a phone tap", () => {
    expect(quickReplyPayload("d1", "button", "offer_accept", "Accept")).toEqual({ driver_id: "d1", kind: "button", button_id: "offer_accept", title: "Accept" });
    expect(quickReplyPayload("d1", "list", "opt:2", "Dock D3")).toEqual({ driver_id: "d1", kind: "list", list_id: "opt:2", title: "Dock D3" });
  });
  it("trims free text and keeps the kind", () => {
    expect(textPayload("d1", "  late by 2 hours ")).toEqual({ driver_id: "d1", kind: "text", text: "late by 2 hours" });
  });
  it("offers the scenarios the brief asks for", () => {
    expect(QUICK_TESTS.map((q) => q.key)).toEqual(["breakdown", "hindi", "options", "arrived", "safety", "stop"]);
    expect(QUICK_TESTS.find((q) => q.key === "stop")?.text).toBe("STOP");
  });
  it("hints the language from the script", () => {
    expect(detectLanguageHint("गाड़ी 2 घंटे लेट है")).toBe("hi");
    expect(detectLanguageHint("నేను ఆలస్యంగా వస్తున్నాను")).toBe("te");
    expect(detectLanguageHint("running late")).toBe("en");
    expect(detectLanguageHint("1234")).toBeNull();
  });
});

function leaves(obj: Record<string, unknown>, prefix = ""): string[] {
  return Object.entries(obj).flatMap(([k, v]) => (v && typeof v === "object" ? leaves(v as Record<string, unknown>, `${prefix}${k}.`) : [`${prefix}${k}`]));
}

describe("wa messages", () => {
  const enKeys = leaves((en as { wa: Record<string, unknown> }).wa).sort();
  const hiKeys = leaves((hi as { wa: Record<string, unknown> }).wa).sort();
  it("has identical English and Hindi keys and the nav label", () => {
    expect(hiKeys).toEqual(enKeys);
    expect((en as { nav: Record<string, string> }).nav.whatsapp).toBeTruthy();
    expect((hi as { nav: Record<string, string> }).nav.whatsapp).toBeTruthy();
  });
  it("defines every literal key the WhatsApp screens use", () => {
    const files: string[] = [];
    const walk = (dir: string) => {
      for (const f of readdirSync(dir)) {
        const p = join(dir, f);
        if (statSync(p).isDirectory()) walk(p);
        else if (/\.tsx?$/.test(f)) files.push(p);
      }
    };
    walk("app/admin/whatsapp");
    walk("components/wa");
    const known = new Set(enKeys);
    const missing: string[] = [];
    for (const f of files) {
      const src = readFileSync(f, "utf8");
      for (const m of src.matchAll(/\bt\(\s*"([a-zA-Z0-9_.]+)"/g)) if (!known.has(m[1])) missing.push(`${f}: ${m[1]}`);
      for (const m of src.matchAll(/"((?:sim|ov|tp|fl|ms|oi)\.[a-zA-Z]+)"/g)) if (!known.has(m[1])) missing.push(`${f}: ${m[1]}`);
    }
    expect(missing).toEqual([]);
  });
  it("covers the dynamic enum keys", () => {
    for (const s of ["received", "queued", "sent", "delivered", "read", "failed", "pending"]) expect(enKeys).toContain(`status.${s}`);
    for (const s of ["draft", "submitted", "approved", "rejected"]) expect(enKeys).toContain(`approval.${s}`);
    for (const s of ["in", "out"]) expect(enKeys).toContain(`direction.${s}`);
    for (const k of ["qBreakdown", "qHindi", "qOptions", "qArrived", "qSafety", "qStop"]) expect(enKeys).toContain(`sim.${k}`);
    for (const k of ["overview", "simulator", "templates", "failures", "messages", "optins"]) expect(enKeys).toContain(`nav.${k}`);
  });
});
