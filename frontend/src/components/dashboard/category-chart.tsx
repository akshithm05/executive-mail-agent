"use client";

import {
  Bar,
  BarChart,
  Cell,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { CATEGORY_ORDER, categoryColor, categoryLabel } from "@/lib/category-meta";
import { EmptyState } from "@/components/shared/empty-state";
import { BarChart3 } from "lucide-react";

interface CategoryChartProps {
  counts: Record<string, number>;
}

export function CategoryChart({ counts }: CategoryChartProps) {
  const data = CATEGORY_ORDER.map((category) => ({
    category,
    label: categoryLabel(category),
    count: counts[category] ?? 0,
    fill: categoryColor(category),
  })).filter((row) => row.count > 0);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Categories</CardTitle>
        <CardDescription>How your inbox breaks down by AI category.</CardDescription>
      </CardHeader>
      <div className="px-2 pb-4">
        {data.length === 0 ? (
          <EmptyState
            icon={BarChart3}
            title="No categorized emails yet"
            description="Once emails are triaged, their categories will show up here."
          />
        ) : (
          <ResponsiveContainer width="100%" height={Math.max(180, data.length * 40)}>
            <BarChart
              data={data}
              layout="vertical"
              margin={{ top: 4, right: 28, bottom: 4, left: 4 }}
              barCategoryGap={10}
            >
              <XAxis type="number" hide />
              <YAxis
                type="category"
                dataKey="label"
                width={120}
                tickLine={false}
                axisLine={false}
                tick={{ fill: "var(--muted-foreground)", fontSize: 12 }}
              />
              <Tooltip
                cursor={{ fill: "var(--muted)" }}
                contentStyle={{
                  background: "var(--card)",
                  border: "1px solid var(--border)",
                  borderRadius: "var(--radius-md)",
                  fontSize: 12,
                  color: "var(--foreground)",
                }}
                labelStyle={{ color: "var(--foreground)", fontWeight: 600 }}
              />
              <Bar dataKey="count" radius={[0, 4, 4, 0]} maxBarSize={18} isAnimationActive>
                {data.map((row) => (
                  <Cell key={row.category} fill={row.fill} />
                ))}
                <LabelList
                  dataKey="count"
                  position="right"
                  style={{ fill: "var(--secondary-ink)", fontSize: 12 }}
                />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>
    </Card>
  );
}
