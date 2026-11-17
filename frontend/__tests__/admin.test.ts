import { describe, expect, it } from "vitest";
import { parseCsv, previewCsv } from "../lib/csv";
import { diffObjects } from "../lib/diff";
import { buildHeaders } from "../lib/api";
import { buildQuery, exportQuery, listQuery, nextSort, sortDirection } from "../lib/query";

describe("query-string building", () => {
  it("skips empty values and encodes the rest", () => {
    expect(buildQuery({ a: 1, b: "", c: undefined, d: null, e: "x y", f: false })).toBe("?a=1&e=x+y&f=false");
    expect(buildQuery({})).toBe("");
  });

  it("builds paged list queries with filters", () => {
    const q = listQuery({ q: "jaipur", sort: "-code", filters: { active: "true", carrier_id: "" }, offset: 50, limit: 25 });
    expect(q).toBe("?limit=25&offset=50&q=jaipur&sort=-code&active=true");
  });

  it("export query has the same filters but no paging", () => {
    expect(exportQuery({ q: "", sort: "code", filters: { status: "PLANNED" } })).toBe("?sort=code&status=PLANNED");
  });

  it("cycles sort asc -> desc -> none", () => {
    expect(nextSort("", "code")).toBe("code");
    expect(nextSort("code", "code")).toBe("-code");
    expect(nextSort("-code", "code")).toBe("");
    expect(nextSort("city", "code")).toBe("code");
    expect(sortDirection("-code", "code")).toBe("descending");
    expect(sortDirection("code", "code")).toBe("ascending");
    expect(sortDirection("city", "code")).toBe("none");
  });
});

describe("idempotency header", () => {
  it("is added to POST/PUT/PATCH only", () => {
    expect(buildHeaders("POST", true, "", "k1")["Idempotency-Key"]).toBe("k1");
    expect(buildHeaders("PATCH", true, "", "k1")["Idempotency-Key"]).toBe("k1");
    expect(buildHeaders("DELETE", false, "", "k1")["Idempotency-Key"]).toBeUndefined();
    expect(buildHeaders("GET", false, "", "k1")["Idempotency-Key"]).toBeUndefined();
  });
});

describe("csv import preview", () => {
  it("parses quoted fields, escaped quotes and CRLF", () => {
    expect(parseCsv('a,b\r\n"x, y","he said ""hi"""\r\n')).toEqual([["a", "b"], ["x, y", 'he said "hi"']]);
  });

  it("reports missing and unknown columns", () => {
    const p = previewCsv("code,city,extra\nF1,Jaipur,z\n", ["code", "facility_name"], ["city"]);
    expect(p.missingColumns).toEqual(["facility_name"]);
    expect(p.unknownColumns).toEqual(["extra"]);
    expect(p.rows).toHaveLength(1);
  });

  it("flags short rows and empty required cells with 1-based line numbers", () => {
    const p = previewCsv("code,name\nF1,Alpha\nF2\nF3,\n", ["code", "name"]);
    expect(p.rowErrors).toEqual([
      { row: 3, message: "Expected 2 columns, found 1" },
      { row: 3, message: "Missing value: name" },
      { row: 4, message: "Missing value: name" },
    ]);
  });
});

describe("audit diff", () => {
  it("lists only changed fields", () => {
    const d = diffObjects({ a: 1, b: "x", c: null }, { a: 1, b: "y", d: 2 });
    expect(d.map((x) => [x.key, x.kind])).toEqual([["b", "changed"], ["d", "added"]]);
  });

  it("treats an insert as all-added", () => {
    expect(diffObjects(null, { a: 1 })).toEqual([{ key: "a", before: undefined, after: 1, kind: "added" }]);
  });
});
