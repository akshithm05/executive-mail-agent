import { describe, expect, it } from "vitest";

import {
  CATEGORY_META,
  CATEGORY_ORDER,
  categoryColor,
  categoryLabel,
} from "@/lib/category-meta";

describe("category-meta", () => {
  it("CATEGORY_ORDER lists exactly the keys of CATEGORY_META, in the same order", () => {
    expect(CATEGORY_ORDER).toEqual(Object.keys(CATEGORY_META));
  });

  it("categoryLabel returns the display label for a known category", () => {
    expect(categoryLabel("action_required")).toBe("Action required");
  });

  it("categoryLabel falls back to the raw value for an unknown category", () => {
    expect(categoryLabel("some_future_category")).toBe("some_future_category");
  });

  it("categoryLabel falls back to 'Uncategorized' for null", () => {
    expect(categoryLabel(null)).toBe("Uncategorized");
  });

  it("categoryColor returns the assigned chart color for a known category", () => {
    expect(categoryColor("meeting_request")).toBe("var(--chart-2)");
  });

  it("categoryColor falls back to the muted color for an unknown/null category", () => {
    expect(categoryColor("something_else")).toBe("var(--muted-foreground)");
    expect(categoryColor(null)).toBe("var(--muted-foreground)");
  });
});
