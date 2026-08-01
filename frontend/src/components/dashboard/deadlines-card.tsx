"use client";

import { useState } from "react";
import { CalendarClock } from "lucide-react";

import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useAsync } from "@/hooks/use-async";
import { listDeadlineEmails } from "@/lib/api";
import { EmailRowDeadline } from "@/components/dashboard/email-row";
import { EmailDetailDialog } from "@/components/dashboard/email-detail-dialog";
import { EmptyState } from "@/components/shared/empty-state";
import { ListRowSkeleton } from "@/components/shared/skeletons";

export function DeadlinesCard() {
  const { data, isLoading, refetch } = useAsync(() => listDeadlineEmails(6), []);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Upcoming deadlines</CardTitle>
        <CardDescription>Emails with a detected deadline, soonest first.</CardDescription>
      </CardHeader>
      <div className="divide-y divide-border/60 px-4 pb-2">
        {isLoading ? (
          Array.from({ length: 3 }).map((_, i) => <ListRowSkeleton key={i} />)
        ) : !data || data.length === 0 ? (
          <EmptyState
            icon={CalendarClock}
            title="No upcoming deadlines"
            description="Deadlines the AI detects in your email will show up here."
          />
        ) : (
          data.map((email, i) => (
            <EmailRowDeadline
              key={email.id}
              email={email}
              onSelect={setSelectedId}
              index={i}
            />
          ))
        )}
      </div>
      <EmailDetailDialog
        emailId={selectedId}
        onClose={() => setSelectedId(null)}
        onChanged={refetch}
      />
    </Card>
  );
}
