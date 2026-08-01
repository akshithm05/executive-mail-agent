"use client";

import {
  AlertTriangle,
  CalendarClock,
  FileText,
  Inbox,
  ListTodo,
  MailOpen,
} from "lucide-react";

import { useAsync } from "@/hooks/use-async";
import { getDashboardSummary } from "@/lib/api";
import { StatTile } from "@/components/dashboard/stat-tile";
import { CategoryChart } from "@/components/dashboard/category-chart";
import { PriorityHeatmap } from "@/components/dashboard/priority-heatmap";
import { UrgentEmailsCard } from "@/components/dashboard/urgent-emails-card";
import { DeadlinesCard } from "@/components/dashboard/deadlines-card";
import { StatTileSkeleton, ChartCardSkeleton } from "@/components/shared/skeletons";
import { ErrorState } from "@/components/shared/empty-state";
import { useCurrentUser } from "@/lib/auth";

export default function OverviewPage() {
  const { user } = useCurrentUser();
  const { data: summary, isLoading, error, refetch } = useAsync(getDashboardSummary, []);

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          Good to see you, {user.display_name.split(" ")[0]}
        </h1>
        <p className="text-sm text-muted-foreground">
          Here&apos;s what&apos;s happening across your inbox.
        </p>
      </div>

      {error ? (
        <ErrorState message="Couldn't load your dashboard summary." onRetry={refetch} />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-3 xl:grid-cols-6">
            {isLoading || !summary ? (
              Array.from({ length: 6 }).map((_, i) => <StatTileSkeleton key={i} />)
            ) : (
              <>
                <StatTile
                  index={0}
                  label="Total emails"
                  value={summary.total_emails}
                  icon={Inbox}
                />
                <StatTile
                  index={1}
                  label="Unread"
                  value={summary.unread_emails}
                  icon={MailOpen}
                />
                <StatTile
                  index={2}
                  label="Urgent"
                  value={summary.urgent_emails}
                  icon={AlertTriangle}
                  tone="critical"
                />
                <StatTile
                  index={3}
                  label="Deadlines"
                  value={summary.upcoming_deadlines}
                  icon={CalendarClock}
                  tone="critical"
                />
                <StatTile
                  index={4}
                  label="Open tasks"
                  value={summary.pending_tasks}
                  icon={ListTodo}
                  tone="good"
                />
                <StatTile
                  index={5}
                  label="Draft replies"
                  value={summary.pending_drafts}
                  icon={FileText}
                />
              </>
            )}
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {isLoading || !summary ? (
              <>
                <ChartCardSkeleton />
                <ChartCardSkeleton />
              </>
            ) : (
              <>
                <CategoryChart counts={summary.category_counts} />
                <PriorityHeatmap cells={summary.priority_heatmap} />
              </>
            )}
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <UrgentEmailsCard />
            <DeadlinesCard />
          </div>
        </>
      )}
    </div>
  );
}
