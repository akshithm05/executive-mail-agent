"use client";

import { format, isPast } from "date-fns";
import { motion } from "framer-motion";

import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import type { Task, TaskPriority } from "@/lib/types";

const PRIORITY_TONE: Record<TaskPriority, string> = {
  low: "bg-good/10 text-good border-good/20",
  medium: "bg-warning/10 text-warning border-warning/20",
  high: "bg-serious/10 text-serious border-serious/20",
  urgent: "bg-critical/10 text-critical border-critical/20",
};

interface TaskRowProps {
  task: Task;
  index?: number;
  onComplete: (id: string) => void;
  onPriorityChange: (id: string, priority: TaskPriority) => void;
}

export function TaskRow({ task, index = 0, onComplete, onPriorityChange }: TaskRowProps) {
  const isDone = task.status === "completed";
  const overdue = !isDone && task.due_at && isPast(new Date(task.due_at));

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, delay: Math.min(index * 0.03, 0.3) }}
      className="flex items-start gap-3 px-2 py-3"
    >
      <Checkbox
        checked={isDone}
        disabled={isDone}
        onCheckedChange={() => onComplete(task.id)}
        className="mt-0.5"
        aria-label={`Mark "${task.title}" complete`}
      />
      <div className="min-w-0 flex-1">
        <p className={cn("text-sm font-medium", isDone && "text-muted-foreground line-through")}>
          {task.title}
        </p>
        {task.description && (
          <p className="mt-0.5 truncate text-xs text-muted-foreground">{task.description}</p>
        )}
        <div className="mt-1.5 flex flex-wrap items-center gap-2">
          {task.due_at && (
            <Badge variant={overdue ? "destructive" : "outline"} className="text-[10px]">
              Due {format(new Date(task.due_at), "MMM d, p")}
            </Badge>
          )}
          {task.created_by === "ai" && (
            <Badge variant="secondary" className="text-[10px]">
              AI-created
            </Badge>
          )}
        </div>
      </div>
      <Select
        value={task.priority}
        disabled={isDone}
        onValueChange={(v) => v && onPriorityChange(task.id, v as TaskPriority)}
      >
        <SelectTrigger
          size="sm"
          className={cn("w-28 border text-xs capitalize", PRIORITY_TONE[task.priority])}
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {(["low", "medium", "high", "urgent"] satisfies TaskPriority[]).map((p) => (
            <SelectItem key={p} value={p} className="capitalize">
              {p}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </motion.div>
  );
}
