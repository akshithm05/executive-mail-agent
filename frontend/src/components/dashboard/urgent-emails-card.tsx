"use client";

import { useState } from "react";
import { AlertTriangle } from "lucide-react";

import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useAsync } from "@/hooks/use-async";
import { listUrgentEmails } from "@/lib/api";
import { EmailRow } from "@/components/dashboard/email-row";
import { EmailDetailDialog } from "@/components/dashboard/email-detail-dialog";
import { EmptyState } from "@/components/shared/empty-state";
import { ListRowSkeleton } from "@/components/shared/skeletons";

export function UrgentEmailsCard() {
  const { data, isLoading, refetch } = useAsync(() => listUrgentEmails(6), []);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Urgent emails</CardTitle>
        <CardDescription>Action-required or high-priority, right now.</CardDescription>
      </CardHeader>
      <div className="divide-y divide-border/60 px-4 pb-2">
        {isLoading ? (
          Array.from({ length: 3 }).map((_, i) => <ListRowSkeleton key={i} />)
        ) : !data || data.length === 0 ? (
          <EmptyState
            icon={AlertTriangle}
            title="Nothing urgent"
            description="You're all caught up on high-priority email."
          />
        ) : (
          data.map((email, i) => (
            <EmailRow key={email.id} email={email} onSelect={setSelectedId} index={i} />
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
