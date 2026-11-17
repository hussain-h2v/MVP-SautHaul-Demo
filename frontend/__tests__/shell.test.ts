import { describe, expect, it } from "vitest";
import { buildHeaders, readCookie } from "../lib/api";
import { filterNav, portals } from "../lib/portals";

describe("csrf header", () => {
  it("adds X-CSRF-Token on unsafe methods only", () => {
    const cookies = "access_token=x; csrf_token=abc%20123";
    expect(readCookie("csrf_token", cookies)).toBe("abc 123");
    expect(buildHeaders("POST", true, cookies)["X-CSRF-Token"]).toBe("abc 123");
    expect(buildHeaders("GET", false, cookies)["X-CSRF-Token"]).toBeUndefined();
  });
});

describe("nav filtering", () => {
  it("hides items whose capability is missing", () => {
    const admin = portals.find((p) => p.slug === "admin")!;
    const nav = filterNav(admin.nav, { capabilities: { analytics: "R", audit_log: "R" } });
    expect(nav.map((n) => n.href)).toEqual(["/admin", "/admin/audit"]);
  });

  it("keeps items without a capability requirement", () => {
    const fac = portals.find((p) => p.slug === "facility")!;
    expect(filterNav(fac.nav, { capabilities: {} }).map((n) => n.href)).toEqual(["/facility"]);
  });
});
