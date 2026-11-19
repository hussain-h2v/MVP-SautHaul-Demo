import { describe, expect, it } from "vitest";
import en from "../messages/en.json";
import hi from "../messages/hi.json";
import { changeTone, formatKpi, heatOpacity, qs, RANGES } from "../lib/insights";

function keys(o: unknown, prefix = ""): string[] {
  if (o === null || typeof o !== "object") return [prefix];
  return Object.entries(o as Record<string, unknown>).flatMap(([k, v]) => keys(v, prefix ? `${prefix}.${k}` : k));
}

describe("insights helpers", () => {
  it("colours a change by whether up is good for that metric", () => {
    expect(changeTone(12, true)).toBe("good");
    expect(changeTone(12, false)).toBe("bad");
    expect(changeTone(-5, false)).toBe("good");
    expect(changeTone(-5, true)).toBe("bad");
    expect(changeTone(0, true)).toBe("neutral");
    expect(changeTone(null, true)).toBe("neutral");
    expect(changeTone(30, null)).toBe("neutral");
  });

  it("formats KPI values by their unit", () => {
    expect(formatKpi("utilisation_pct", 56.123)).toBe("56.1%");
    expect(formatKpi("on_time_rate", 75)).toBe("75.0%");
    expect(formatKpi("avg_wait_min", 20.4)).toBe("20 min");
    expect(formatKpi("lost_hours", 3.25)).toBe("3.3 h");
    expect(formatKpi("loads_completed", 2284)).toBe((2284).toLocaleString());
    expect(formatKpi("avg_cost", 1.5)).toBe("1.5");
  });

  it("keeps heat opacity within a readable range", () => {
    expect(heatOpacity(0)).toBe(0.12);
    expect(heatOpacity(100)).toBe(1);
    expect(heatOpacity(250)).toBe(1);
    expect(heatOpacity(-10)).toBe(0.12);
    expect(heatOpacity(50)).toBeGreaterThan(heatOpacity(20));
  });

  it("builds query strings without empty values", () => {
    expect(qs({ range: "7d", facility_id: "", carrier_id: null, lang: undefined })).toBe("?range=7d");
    expect(qs({})).toBe("");
  });

  it("offers the five required periods", () => {
    expect(RANGES).toEqual(["1d", "3d", "7d", "3w", "1m"]);
  });
});

describe("insights strings", () => {
  const enKeys = keys((en as Record<string, unknown>).insights).sort();
  const hiKeys = keys((hi as Record<string, unknown>).insights).sort();

  it("has the same keys in English and Hindi", () => {
    expect(hiKeys).toEqual(enKeys);
  });

  it("has a label for every KPI, period and weekday", () => {
    const e = (en as unknown as { insights: { kpi: Record<string, string>; range: Record<string, string>; weekday: Record<string, string> } }).insights;
    for (const k of ["utilisation_pct", "on_time_rate", "avg_wait_min", "no_show_rate", "loads_completed", "requests", "escalations", "bot_resolution_rate", "decline_rate"]) expect(e.kpi[k]).toBeTruthy();
    for (const r of RANGES) expect(e.range[r]).toBeTruthy();
    for (let d = 1; d <= 7; d++) expect(e.weekday[String(d)]).toBeTruthy();
  });

  it("keeps placeholders identical across languages", () => {
    const flat = (o: unknown): Record<string, string> => Object.fromEntries(keys(o).map((k) => [k, k.split(".").reduce((a: unknown, p) => (a as Record<string, unknown>)[p], o) as string]));
    const e = flat((en as Record<string, unknown>).insights);
    const h = flat((hi as Record<string, unknown>).insights);
    for (const k of Object.keys(e)) expect((h[k].match(/\{\w+\}/g) ?? []).sort()).toEqual((e[k].match(/\{\w+\}/g) ?? []).sort());
  });
});
