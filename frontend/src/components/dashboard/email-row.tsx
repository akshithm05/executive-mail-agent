"use client";

import { formatDistanceToNow } from "date-fns";
import { motion } from "framer-motion";
import { Paperclip, Star } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { categoryLabel } from "@/lib/category-meta";
import type { EmailSummary } from "@/lib/types";

interface EmailRowProps {
  email: EmailSummary;
  onSelect: (id: string) => void;
  index?: number;
}

function priorityTone(score: number | null): string {
  if (score === null) return "bg-muted-foreground/40";
  if (score >= 0.8) return "bg-critical";
  if (score >= 0.6) return "bg-serious";
  if (score >= 0.4) return "bg-warning";
  return "bg-good";
}

export function EmailRow({ email, onSelect, index = 0 }: EmailRowProps) {
  return (
    <motion.button
      initial={{ opacity: 0, x: -6 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.25, delay: Math.min(index * 0.03, 0.3) }}
      onClick={() => onSelect(email.id)}
      className="flex w-full items-start gap-3 rounded-lg px-2 py-2.5 text-left transition-colors hover:bg-accent"
    >
      <span
        aria-hidden
        className={cn(
          "mt-1.5 h-2 w-2 shrink-0 rounded-full",
          priorityTone(email.priority_score),
        )}
        title={
          email.priority_score !== null
            ? `Priority ${Math.round(email.priority_score * 100)}%`
            : "Priority unknown"
        }
      />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p
            className={cn(
              "truncate text-sm",
              email.is_read ? "font-normal text-foreground/80" : "font-semibold",
            )}
          >
            {email.subject || "(no subject)"}
          </p>
          {email.is_starred && (
            <Star className="h-3 w-3 shrink-0 fill-warning text-warning" />
          )}
        </div>
        <p className="truncate text-xs text-muted-foreground">{email.from_address}</p>
      </div>
      <div className="flex shrink-0 flex-col items-end gap-1">
        <span className="text-[11px] text-muted-foreground">
          {formatDistanceToNow(new Date(email.received_at), { addSuffix: true })}
        </span>
        {email.category && (
          <Badge variant="secondary" className="text-[10px]">
            {categoryLabel(email.category)}
          </Badge>
        )}
      </div>
    </motion.button>
  );
}

export function EmailRowDeadline({ email, onSelect, index = 0 }: EmailRowProps) {
  return (
    <motion.button
      initial={{ opacity: 0, x: -6 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.25, delay: Math.min(index * 0.03, 0.3) }}
      onClick={() => onSelect(email.id)}
      className="flex w-full items-center gap-3 rounded-lg px-2 py-2.5 text-left transition-colors hover:bg-accent"
    >
      <Paperclip className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{email.subject || "(no subject)"}</p>
        <p className="truncate text-xs text-muted-foreground">{email.from_address}</p>
      </div>
      {email.deadline_at && (
        <Badge variant="outline" className="shrink-0 text-[10px] tabular-nums">
          {formatDistanceToNow(new Date(email.deadline_at), { addSuffix: true })}
        </Badge>
      )}
    </motion.button>
  );
}
