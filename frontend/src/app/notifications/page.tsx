"use client";

import { useState } from "react";
import { formatDistanceToNow } from "date-fns";
import { motion } from "framer-motion";
import { Bell, BellRing, CalendarClock, ListTodo, Send } from "lucide-react";

import { useAsync } from "@/hooks/use-async";
import { listNotifications, markNotificationRead } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { EmptyState, ErrorState } from "@/components/shared/empty-state";
import { ListRowSkeleton } from "@/components/shared/skeletons";
import { cn } from "@/lib/utils";
import type { AppNotification } from "@/lib/types";

const TYPE_ICON: Record<string, typeof Bell> = {
  reminder: CalendarClock,
  draft_ready: Send,
  high_priority_email: BellRing,
  task: ListTodo,
};

export default function NotificationsPage() {
  const [unreadOnly, setUnreadOnly] = useState(false);
  const { data, isLoading, error, refetch } = useAsync(
    () => listNotifications(unreadOnly),
    [unreadOnly],
  );

  async function handleClick(notification: AppNotification) {
    if (!notification.is_read) {
      await markNotificationRead(notification.id);
      refetch();
    }
  }

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Notifications</h1>
          <p className="text-sm text-muted-foreground">
            Reminders, high-priority alerts, and drafts ready for review.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Label htmlFor="unread-only" className="text-xs text-muted-foreground">
            Unread only
          </Label>
          <Switch id="unread-only" checked={unreadOnly} onCheckedChange={setUnreadOnly} />
        </div>
      </div>

      <Card>
        <CardContent className="divide-y divide-border/60 px-3">
          {error ? (
            <ErrorState message="Couldn't load notifications." onRetry={refetch} />
          ) : isLoading ? (
            Array.from({ length: 6 }).map((_, i) => <ListRowSkeleton key={i} />)
          ) : !data || data.length === 0 ? (
            <EmptyState
              icon={Bell}
              title="You're all caught up"
              description="New reminders and alerts will show up here."
            />
          ) : (
            data.map((notification, i) => {
              const Icon = TYPE_ICON[notification.type] ?? Bell;
              return (
                <motion.button
                  key={notification.id}
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.25, delay: Math.min(i * 0.03, 0.3) }}
                  onClick={() => handleClick(notification)}
                  className={cn(
                    "flex w-full items-start gap-3 rounded-lg px-2 py-3 text-left transition-colors hover:bg-accent",
                    !notification.is_read && "bg-primary/5",
                  )}
                >
                  <div
                    className={cn(
                      "mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full",
                      notification.is_read
                        ? "bg-muted text-muted-foreground"
                        : "bg-primary/10 text-primary",
                    )}
                  >
                    <Icon className="h-4 w-4" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p
                      className={cn(
                        "text-sm",
                        notification.is_read ? "font-normal" : "font-semibold",
                      )}
                    >
                      {notification.title}
                    </p>
                    {notification.body && (
                      <p className="mt-0.5 truncate text-xs text-muted-foreground">
                        {notification.body}
                      </p>
                    )}
                  </div>
                  <span className="shrink-0 text-[11px] text-muted-foreground">
                    {formatDistanceToNow(new Date(notification.created_at), {
                      addSuffix: true,
                    })}
                  </span>
                </motion.button>
              );
            })
          )}
        </CardContent>
      </Card>
    </div>
  );
}
