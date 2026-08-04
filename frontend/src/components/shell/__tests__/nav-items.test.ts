import { describe, expect, it } from "vitest";

import { NAV_ITEMS } from "@/components/shell/nav-items";

describe("NAV_ITEMS", () => {
  it("has one entry per top-level route, each with a unique href", () => {
    const hrefs = NAV_ITEMS.map((item) => item.href);
    expect(new Set(hrefs).size).toBe(hrefs.length);
  });

  it("every entry has a non-empty label and an icon component", () => {
    for (const item of NAV_ITEMS) {
      expect(item.label.length).toBeGreaterThan(0);
      expect(item.icon).toBeDefined();
    }
  });

  it("includes the dashboard overview as the first item, at the root route", () => {
    expect(NAV_ITEMS[0]).toMatchObject({ href: "/", label: "Overview" });
  });
});
