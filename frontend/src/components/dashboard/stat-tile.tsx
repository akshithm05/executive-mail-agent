"use client";

import type { LucideIcon } from "lucide-react";
import { motion } from "framer-motion";

import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { AnimatedNumber } from "@/components/shared/animated-number";
import { cn } from "@/lib/utils";

interface StatTileProps {
  label: string;
  value: number;
  icon: LucideIcon;
  tone?: "default" | "critical" | "good";
  index?: number;
}

const TONE_CLASSES: Record<NonNullable<StatTileProps["tone"]>, string> = {
  default: "bg-primary/10 text-primary",
  critical: "bg-critical/10 text-critical",
  good: "bg-good/10 text-good",
};

export function StatTile({
  label,
  value,
  icon: Icon,
  tone = "default",
  index = 0,
}: StatTileProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: index * 0.05, ease: [0.16, 1, 0.3, 1] }}
    >
      <Card className="gap-3">
        <CardHeader className="flex-row items-center justify-between pb-0">
          <span className="text-sm text-muted-foreground">{label}</span>
          <div className={cn("flex h-8 w-8 items-center justify-center rounded-lg", TONE_CLASSES[tone])}>
            <Icon className="h-4 w-4" />
          </div>
        </CardHeader>
        <CardContent>
          <AnimatedNumber value={value} className="text-2xl font-semibold tabular-nums" />
        </CardContent>
      </Card>
    </motion.div>
  );
}
