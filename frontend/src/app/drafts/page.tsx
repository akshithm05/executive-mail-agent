"use client";

import { useState } from "react";
import { Send } from "lucide-react";

import { useAsync } from "@/hooks/use-async";
import { listDraftReplies } from "@/lib/api";
import { DraftCard } from "@/components/drafts/draft-card";
import { EmptyState, ErrorState } from "@/components/shared/empty-state";
import { Card, CardContent, CardFooter, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

type StatusFilter = "draft" | "approved" | "discarded" | "all";

function DraftCardSkeleton() {
  return (
    <Card>
      <CardHeader className="space-y-2">
        <Skeleton className="h-4 w-1/2" />
        <Skeleton className="h-3 w-1/3" />
      </CardHeader>
      <CardContent className="space-y-2">
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-2/3" />
      </CardContent>
      <CardFooter className="gap-2">
        <Skeleton className="h-8 w-20" />
        <Skeleton className="h-8 w-24" />
        <Skeleton className="h-8 w-20" />
      </CardFooter>
    </Card>
  );
}

export default function DraftsPage() {
  const [filter, setFilter] = useState<StatusFilter>("draft");

  const { data, isLoading, error, refetch } = useAsync(
    () => listDraftReplies(filter === "all" ? undefined : filter),
    [filter],
  );

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Draft replies</h1>
        <p className="text-sm text-muted-foreground">
          Every draft is editable and never sends on its own — review, edit, regenerate, or
          approve.
        </p>
      </div>

      <Tabs value={filter} onValueChange={(v) => setFilter(v as StatusFilter)}>
        <TabsList>
          <TabsTrigger value="draft">Needs review</TabsTrigger>
          <TabsTrigger value="approved">Approved</TabsTrigger>
          <TabsTrigger value="discarded">Discarded</TabsTrigger>
          <TabsTrigger value="all">All</TabsTrigger>
        </TabsList>
      </Tabs>

      {error ? (
        <ErrorState message="Couldn't load draft replies." onRetry={refetch} />
      ) : isLoading ? (
        <div className="flex flex-col gap-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <DraftCardSkeleton key={i} />
          ))}
        </div>
      ) : !data || data.length === 0 ? (
        <Card>
          <EmptyState
            icon={Send}
            title="No draft replies here"
            description="AI-drafted replies to your email will appear here for review."
          />
        </Card>
      ) : (
        <div className="flex flex-col gap-4">
          {data.map((draft, i) => (
            <DraftCard key={draft.id} draft={draft} index={i} onChanged={refetch} />
          ))}
        </div>
      )}
    </div>
  );
}
