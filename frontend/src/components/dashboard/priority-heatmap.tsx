"use client";

import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/shared/empty-state";
import { CATEGORY_ORDER, categoryLabel } from "@/lib/category-meta";
import type { PriorityHeatmapCell } from "@/lib/types";
import { Flame } from "lucide-react";

const BANDS = ["0-20", "20-40", "40-60", "60-80", "80-100"];
const BAND_LABELS: Record<string, string> = {
  "0-20": "Low",
  "20-40": "",
  "40-60": "Medium",
  "60-80": "",
  "80-100": "High",
};

interface PriorityHeatmapProps {
  cells: PriorityHeatmapCell[];
}

export function PriorityHeatmap({ cells }: PriorityHeatmapProps) {
  const byKey = new Map(cells.map((c) => [`${c.category}:${c.priority_band}`, c.count]));
  const categories = CATEGORY_ORDER.filter((cat) =>
    cells.some((c) => c.category === cat),
  );
  const maxCount = Math.max(1, ...cells.map((c) => c.count));

  return (
    <Card>
      <CardHeader>
        <CardTitle>Priority heatmap</CardTitle>
        <CardDescription>Email volume by category and priority score.</CardDescription>
      </CardHeader>
      <div className="px-6 pb-6">
        {categories.length === 0 ? (
          <EmptyState
            icon={Flame}
            title="No priority data yet"
            description="Priority scores appear once the AI agent triages your inbox."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[420px] border-separate border-spacing-1.5">
              <thead>
                <tr>
                  <th className="w-32" />
                  {BANDS.map((band) => (
                    <th
                      key={band}
                      className="pb-1.5 text-center text-[11px] font-medium text-muted-foreground"
                    >
                      {BAND_LABELS[band] || <span aria-hidden>&nbsp;</span>}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {categories.map((category) => (
                  <tr key={category}>
                    <th
                      scope="row"
                      className="pr-2 text-left text-xs font-medium text-foreground"
                    >
                      {categoryLabel(category)}
                    </th>
                    {BANDS.map((band) => {
                      const count = byKey.get(`${category}:${band}`) ?? 0;
                      const pct = Math.round((count / maxCount) * 100);
                      return (
                        <td key={band} className="p-0">
                          <div
                            title={`${categoryLabel(category)} · ${band}%: ${count} email${count === 1 ? "" : "s"}`}
                            className="flex h-11 w-full items-center justify-center rounded-md text-xs font-medium tabular-nums transition-colors"
                            style={{
                              backgroundColor:
                                count === 0
                                  ? "var(--muted)"
                                  : `color-mix(in srgb, var(--primary) ${Math.max(pct, 18)}%, var(--card))`,
                              color:
                                count > 0 && pct > 55
                                  ? "var(--primary-foreground)"
                                  : "var(--foreground)",
                            }}
                          >
                            {count > 0 ? count : ""}
                          </div>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Card>
  );
}
