import type { EmailCategory } from "@/lib/types";

/**
 * Display metadata for each email category, in a fixed order.
 *
 * The order here IS the color-assignment order (`--chart-1` through
 * `--chart-7`, slot 1 = first entry) -- the dataviz skill's validated
 * palette was checked for adjacent-pair CVD safety in exactly this
 * sequence, so any chart that lists categories in this order (never
 * re-sorted by count/alphabetically) keeps that guarantee. See
 * `references/palette.md`'s categorical table.
 */
export const CATEGORY_META: Record<
  EmailCategory,
  { label: string; colorVar: string }
> = {
  action_required: { label: "Action required", colorVar: "var(--chart-1)" },
  meeting_request: { label: "Meeting request", colorVar: "var(--chart-2)" },
  fyi: { label: "FYI", colorVar: "var(--chart-3)" },
  newsletter: { label: "Newsletter", colorVar: "var(--chart-4)" },
  personal: { label: "Personal", colorVar: "var(--chart-5)" },
  spam: { label: "Spam", colorVar: "var(--chart-6)" },
  other: { label: "Other", colorVar: "var(--chart-7)" },
};

export const CATEGORY_ORDER: EmailCategory[] = [
  "action_required",
  "meeting_request",
  "fyi",
  "newsletter",
  "personal",
  "spam",
  "other",
];

export function categoryLabel(category: string | null): string {
  if (category && category in CATEGORY_META) {
    return CATEGORY_META[category as EmailCategory].label;
  }
  return category ?? "Uncategorized";
}

export function categoryColor(category: string | null): string {
  if (category && category in CATEGORY_META) {
    return CATEGORY_META[category as EmailCategory].colorVar;
  }
  return "var(--muted-foreground)";
}
