"use client";

import { useState } from "react";
import { ListTodo } from "lucide-react";

import { useAsync } from "@/hooks/use-async";
import { completeTask, editTask, listTasks } from "@/lib/api";
import { TaskRow } from "@/components/tasks/task-row";
import { ListRowSkeleton } from "@/components/shared/skeletons";
import { EmptyState, ErrorState } from "@/components/shared/empty-state";
import { Card } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { TaskPriority, TaskStatus } from "@/lib/types";

type StatusFilter = "open" | TaskStatus | "all";

export default function TasksPage() {
  const [filter, setFilter] = useState<StatusFilter>("open");

  const { data, isLoading, error, refetch } = useAsync(async () => {
    if (filter === "all") return listTasks();
    if (filter === "open") {
      const [pending, inProgress] = await Promise.all([
        listTasks("pending"),
        listTasks("in_progress"),
      ]);
      return [...pending, ...inProgress].sort((a, b) =>
        (a.due_at ?? "9999").localeCompare(b.due_at ?? "9999"),
      );
    }
    return listTasks(filter);
  }, [filter]);

  async function handleComplete(id: string) {
    await completeTask(id);
    refetch();
  }

  async function handlePriorityChange(id: string, priority: TaskPriority) {
    await editTask(id, { priority });
    refetch();
  }

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Tasks</h1>
        <p className="text-sm text-muted-foreground">
          Action items the AI extracted from your email, plus anything you&apos;ve added.
        </p>
      </div>

      <Tabs value={filter} onValueChange={(v) => setFilter(v as StatusFilter)}>
        <TabsList>
          <TabsTrigger value="open">Open</TabsTrigger>
          <TabsTrigger value="completed">Completed</TabsTrigger>
          <TabsTrigger value="cancelled">Cancelled</TabsTrigger>
          <TabsTrigger value="all">All</TabsTrigger>
        </TabsList>
      </Tabs>

      <Card>
        <div className="divide-y divide-border/60 px-3 py-1">
          {error ? (
            <ErrorState message="Couldn't load your tasks." onRetry={refetch} />
          ) : isLoading ? (
            Array.from({ length: 6 }).map((_, i) => <ListRowSkeleton key={i} />)
          ) : !data || data.length === 0 ? (
            <EmptyState
              icon={ListTodo}
              title="No tasks here"
              description="Tasks the AI extracts from your email will show up here."
            />
          ) : (
            data.map((task, i) => (
              <TaskRow
                key={task.id}
                task={task}
                index={i}
                onComplete={handleComplete}
                onPriorityChange={handlePriorityChange}
              />
            ))
          )}
        </div>
      </Card>
    </div>
  );
}
