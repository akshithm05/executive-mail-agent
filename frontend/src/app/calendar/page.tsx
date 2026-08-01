"use client";

import { format, isToday, isTomorrow } from "date-fns";
import { CalendarDays, Clock, MapPin } from "lucide-react";
import { motion } from "framer-motion";

import { useAsync } from "@/hooks/use-async";
import { listUpcomingEvents } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ListRowSkeleton } from "@/components/shared/skeletons";
import { EmptyState, ErrorState } from "@/components/shared/empty-state";
import type { CalendarEvent } from "@/lib/types";

function dayLabel(dateKey: string) {
  const date = new Date(dateKey);
  if (isToday(date)) return "Today";
  if (isTomorrow(date)) return "Tomorrow";
  return format(date, "EEEE, MMMM d");
}

function groupByDay(events: CalendarEvent[]): Map<string, CalendarEvent[]> {
  const groups = new Map<string, CalendarEvent[]>();
  for (const event of events) {
    const key = format(new Date(event.start_at), "yyyy-MM-dd");
    groups.set(key, [...(groups.get(key) ?? []), event]);
  }
  return groups;
}

export default function CalendarPage() {
  const { data, isLoading, error, refetch } = useAsync(() => listUpcomingEvents(100), []);

  const groups = data ? groupByDay(data) : null;

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Calendar</h1>
        <p className="text-sm text-muted-foreground">
          Upcoming events, including everything the AI suggested from your email.
        </p>
      </div>

      {error ? (
        <ErrorState message="Couldn't load your calendar." onRetry={refetch} />
      ) : isLoading ? (
        <Card>
          <CardContent className="divide-y divide-border/60 px-3">
            {Array.from({ length: 5 }).map((_, i) => (
              <ListRowSkeleton key={i} />
            ))}
          </CardContent>
        </Card>
      ) : !groups || groups.size === 0 ? (
        <Card>
          <EmptyState
            icon={CalendarDays}
            title="Nothing on your calendar"
            description="Meetings the AI detects in your email will appear here."
          />
        </Card>
      ) : (
        <div className="flex flex-col gap-5">
          {Array.from(groups.entries()).map(([dateKey, events], groupIndex) => (
            <motion.div
              key={dateKey}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3, delay: groupIndex * 0.05 }}
            >
              <h2 className="mb-2 text-sm font-semibold text-muted-foreground">
                {dayLabel(dateKey)}
              </h2>
              <Card>
                <CardContent className="divide-y divide-border/60 px-4">
                  {events.map((event) => (
                    <div key={event.id} className="flex items-start gap-3 py-3">
                      <div className="flex w-16 shrink-0 flex-col items-start pt-0.5 text-xs text-muted-foreground">
                        <span className="flex items-center gap-1">
                          <Clock className="h-3 w-3" />
                          {event.all_day ? "All day" : format(new Date(event.start_at), "p")}
                        </span>
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium">{event.title}</p>
                        {event.location && (
                          <p className="mt-0.5 flex items-center gap-1 truncate text-xs text-muted-foreground">
                            <MapPin className="h-3 w-3 shrink-0" />
                            {event.location}
                          </p>
                        )}
                      </div>
                      <Badge
                        variant={event.status === "tentative" ? "outline" : "secondary"}
                        className="shrink-0 text-[10px] capitalize"
                      >
                        {event.status}
                      </Badge>
                    </div>
                  ))}
                </CardContent>
              </Card>
            </motion.div>
          ))}
        </div>
      )}
    </div>
  );
}
