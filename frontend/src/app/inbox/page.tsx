"use client";

import { useState } from "react";
import { Inbox as InboxIcon } from "lucide-react";

import { useAsync } from "@/hooks/use-async";
import { listEmails } from "@/lib/api";
import { EmailRow } from "@/components/dashboard/email-row";
import { EmailDetailDialog } from "@/components/dashboard/email-detail-dialog";
import { ListRowSkeleton } from "@/components/shared/skeletons";
import { EmptyState, ErrorState } from "@/components/shared/empty-state";
import { Card } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { CATEGORY_ORDER, categoryLabel } from "@/lib/category-meta";

type ReadFilter = "all" | "unread" | "read";

export default function InboxPage() {
  const [category, setCategory] = useState<string>("all");
  const [readFilter, setReadFilter] = useState<ReadFilter>("all");
  const [sort, setSort] = useState<"recent" | "priority">("recent");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const { data, isLoading, error, refetch } = useAsync(
    () =>
      listEmails({
        category: category === "all" ? undefined : category,
        is_read: readFilter === "all" ? undefined : readFilter === "read",
        sort,
        limit: 100,
      }),
    [category, readFilter, sort],
  );

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-5">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">Inbox</h1>
        <p className="text-sm text-muted-foreground">
          Every email the AI has triaged, filterable by category and priority.
        </p>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <Tabs value={readFilter} onValueChange={(v) => setReadFilter(v as ReadFilter)}>
          <TabsList>
            <TabsTrigger value="all">All</TabsTrigger>
            <TabsTrigger value="unread">Unread</TabsTrigger>
            <TabsTrigger value="read">Read</TabsTrigger>
          </TabsList>
        </Tabs>

        <div className="flex items-center gap-2">
          <Select value={category} onValueChange={(v) => v && setCategory(v)}>
            <SelectTrigger className="w-44">
              <SelectValue placeholder="Category" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All categories</SelectItem>
              {CATEGORY_ORDER.map((c) => (
                <SelectItem key={c} value={c}>
                  {categoryLabel(c)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={sort} onValueChange={(v) => v && setSort(v as typeof sort)}>
            <SelectTrigger className="w-36">
              <SelectValue placeholder="Sort" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="recent">Most recent</SelectItem>
              <SelectItem value="priority">Priority</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      <Card>
        <div className="divide-y divide-border/60 px-3 py-1">
          {error ? (
            <ErrorState message="Couldn't load your inbox." onRetry={refetch} />
          ) : isLoading ? (
            Array.from({ length: 8 }).map((_, i) => <ListRowSkeleton key={i} />)
          ) : !data || data.length === 0 ? (
            <EmptyState
              icon={InboxIcon}
              title="No emails match these filters"
              description="Try a different category or read status."
            />
          ) : (
            data.map((email, i) => (
              <EmailRow key={email.id} email={email} onSelect={setSelectedId} index={i} />
            ))
          )}
        </div>
      </Card>

      <EmailDetailDialog
        emailId={selectedId}
        onClose={() => setSelectedId(null)}
        onChanged={refetch}
      />
    </div>
  );
}
