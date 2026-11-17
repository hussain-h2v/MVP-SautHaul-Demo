import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  blankStep, budgetState, compareDeltas, disagreementCount, formatMoney, formatPercent, formatRate, languageChartData, moveStep,
  pathNodes, pathSummary, removeStep, sameSteps, stepRole, stepsPayload, templateVariables,
} from "../lib/ai";
import type { EvalCompare, EvalRun, PathEntry } from "../lib/ai-types";
import en from "../messages/en.json";
import hi from "../messages/hi.json";

describe("route chain reorder", () => {
  it("moves a step and keeps the rest in order", () => {
    expect(moveStep(["a", "b", "c"], 2, 0)).toEqual(["c", "a", "b"]);
    expect(moveStep(["a", "b", "c"], 0, 1)).toEqual(["b", "a", "c"]);
  });
  it("ignores out-of-range or no-op moves and never mutates", () => {
    const src = ["a", "b"];
    expect(moveStep(src, 0, 5)).toBe(src);
    expect(moveStep(src, 1, 1)).toBe(src);
    moveStep(src, 0, 1);
    expect(src).toEqual(["a", "b"]);
  });
  it("removes by index and names the roles", () => {
    expect(removeStep(["a", "b", "c"], 1)).toEqual(["a", "c"]);
    expect([0, 1, 2, 3].map(stepRole)).toEqual(["primary", "secondary", "tertiary", "other"]);
  });
  it("detects unsaved changes from order, ignoring server-only fields", () => {
    const a = { ...blankStep("m1"), id: "s1", priority: 1, model_name: "x" };
    const b = { ...blankStep("m2"), id: "s2", priority: 2 };
    expect(sameSteps([a, b], [{ ...a, id: "other" }, b])).toBe(true);
    expect(sameSteps([a, b], [b, a])).toBe(false);
    expect(stepsPayload([a])[0]).not.toHaveProperty("id");
  });
});

describe("budget formatting", () => {
  it("derives state from spend and threshold", () => {
    expect(budgetState(10, 100, 0.8)).toBe("ok");
    expect(budgetState(80, 100, 0.8)).toBe("alert");
    expect(budgetState(100, 100, 0.8)).toBe("exhausted");
    expect(budgetState(5, 0, 0.8)).toBe("ok");
  });
  it("formats percent, money and rates", () => {
    expect(formatPercent(25, 100)).toBe("25%");
    expect(formatPercent(1, 0)).toBe("0%");
    expect(formatMoney(0.0123)).toBe("$0.0123");
    expect(formatMoney(12.5)).toBe("$12.50");
    expect(formatMoney(null)).toBe("—");
    expect(formatRate(0.025)).toBe("2.5%");
    expect(formatRate(0.5)).toBe("50%");
  });
});

describe("fallback path model", () => {
  const path: PathEntry[] = [
    { step: 1, provider: "A", model: "m1", outcome: "error:timeout", forced: true },
    { step: 2, provider: "B", model: "m2", outcome: "skipped:circuit_open" },
    { step: 3, provider: "C", model: "m3", outcome: "ok" },
  ];
  it("always gives a text code besides the tone", () => {
    const n = pathNodes(path);
    expect(n.map((x) => x.tone)).toEqual(["failed", "skipped", "ok"]);
    expect(n.map((x) => x.code)).toEqual(["timeout", "circuit_open", "ok"]);
    expect(n[0].forced).toBe(true);
  });
  it("summarises as text", () => {
    expect(pathSummary(path)).toBe("A / m1 (timeout) → B / m2 (circuit_open) → C / m3 (ok)");
    expect(pathNodes([])).toEqual([]);
  });
});

const run = (id: string, label: string, accuracy: number, latency: number, cost: number, by: Record<string, number>): EvalRun => ({
  id, label, model_id: null, status: "done", total: 10, correct: Math.round(accuracy * 10), accuracy, avg_latency_ms: latency,
  total_cost: cost, by_language: by, created_at: "2026-01-01T00:00:00Z",
});

describe("eval compare", () => {
  const runs = [run("r1", "base", 0.7, 400, 0.01, { en: 1, hi: 0.4 }), run("r2", "new", 0.9, 300, 0.02, { en: 1, hi: 0.8, te: 0.7 })];
  it("computes deltas against the first run", () => {
    expect(compareDeltas(runs)).toEqual([
      { accuracy: 0, avg_latency_ms: 0, total_cost: 0 },
      { accuracy: 0.2, avg_latency_ms: -100, total_cost: 0.01 },
    ]);
    expect(compareDeltas([])).toEqual([]);
  });
  it("builds per-language chart rows with one column per run", () => {
    expect(languageChartData(runs)).toEqual([
      { language: "en", base: 100, new: 100 },
      { language: "hi", base: 40, new: 80 },
      { language: "te", base: 0, new: 70 },
    ]);
  });
  it("counts cases where runs disagree", () => {
    const c: EvalCompare = {
      runs,
      differences: [
        { case_id: "1", text: "x", language: "hi", expected: {}, results: [{ run_id: "r1", got: null, correct: false }, { run_id: "r2", got: null, correct: true }] },
        { case_id: "2", text: "y", language: "hi", expected: {}, results: [{ run_id: "r1", got: null, correct: false }, { run_id: "r2", got: null, correct: false }] },
      ],
    };
    expect(disagreementCount(c)).toBe(1);
  });
});

describe("prompt variables", () => {
  it("finds unique {{placeholders}}", () => {
    expect(templateVariables("Hi {{ name }}, ETA {{eta}} {{name}}")).toEqual(["name", "eta"]);
    expect(templateVariables("no vars")).toEqual([]);
  });
});

function leaves(obj: Record<string, unknown>, prefix = ""): string[] {
  return Object.entries(obj).flatMap(([k, v]) => (v && typeof v === "object" ? leaves(v as Record<string, unknown>, `${prefix}${k}.`) : [`${prefix}${k}`]));
}

describe("ai messages", () => {
  const enKeys = leaves((en as { ai: Record<string, unknown> }).ai).sort();
  const hiKeys = leaves((hi as { ai: Record<string, unknown> }).ai).sort();
  it("has identical English and Hindi keys", () => {
    expect(hiKeys).toEqual(enKeys);
  });
  it("defines every literal key the AI screens use", () => {
    const files: string[] = [];
    const walk = (dir: string) => {
      for (const f of readdirSync(dir)) {
        const p = join(dir, f);
        if (statSync(p).isDirectory()) walk(p);
        else if (/\.tsx?$/.test(f)) files.push(p);
      }
    };
    walk("app/admin/ai");
    walk("components/ai");
    const known = new Set(enKeys);
    const missing: string[] = [];
    for (const f of files) {
      const src = readFileSync(f, "utf8");
      for (const m of src.matchAll(/\bt\(\s*"([a-zA-Z0-9_.]+)"/g)) if (!known.has(m[1])) missing.push(`${f}: ${m[1]}`);
    }
    expect(missing).toEqual([]);
  });
});
