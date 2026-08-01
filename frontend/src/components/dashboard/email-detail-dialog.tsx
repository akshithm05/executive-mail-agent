"use client";

import { format } from "date-fns";
import { Star } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useAsync } from "@/hooks/use-async";
import { getEmail, markEmailRead, toggleEmailStar } from "@/lib/api";
import { categoryLabel } from "@/lib/category-meta";
import { cn } from "@/lib/utils";

interface EmailDetailDialogProps {
  emailId: string | null;
  onClose: () => void;
  onChanged?: () => void;
}

export function EmailDetailDialog({ emailId, onClose, onChanged }: EmailDetailDialogProps) {
  const { data: email, isLoading, refetch } = useAsync(async () => {
    if (!emailId) return null;
    const result = await getEmail(emailId);
    if (!result.is_read) {
      await markEmailRead(emailId);
      onChanged?.();
    }
    return result;
  }, [emailId]);

  return (
    <Dialog open={!!emailId} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[80vh] overflow-y-auto sm:max-w-xl">
        {isLoading || !email ? (
          <div className="space-y-3">
            <Skeleton className="h-5 w-3/4" />
            <Skeleton className="h-3 w-1/2" />
            <Skeleton className="h-32 w-full" />
          </div>
        ) : (
          <>
            <DialogHeader>
              <div className="flex items-start justify-between gap-4">
                <DialogTitle className="text-left">
                  {email.subject || "(no subject)"}
                </DialogTitle>
                <Button
                  variant="ghost"
                  size="icon"
                  className="shrink-0"
                  aria-label="Toggle star"
                  onClick={async () => {
                    await toggleEmailStar(email.id);
                    refetch();
                    onChanged?.();
                  }}
                >
                  <Star
                    className={cn(
                      "h-4 w-4",
                      email.is_starred && "fill-warning text-warning",
                    )}
                  />
                </Button>
              </div>
              <DialogDescription className="text-left">
                From <span className="font-medium text-foreground">{email.from_address}</span>{" "}
                · {format(new Date(email.received_at), "PPP p")}
              </DialogDescription>
            </DialogHeader>

            <div className="flex flex-wrap items-center gap-2">
              {email.category && (
                <Badge variant="secondary">{categoryLabel(email.category)}</Badge>
              )}
              {email.priority_score !== null && (
                <Badge variant="outline">
                  Priority {Math.round(email.priority_score * 100)}%
                </Badge>
              )}
              {email.has_deadline && email.deadline_at && (
                <Badge variant="outline">
                  Due {format(new Date(email.deadline_at), "PP p")}
                </Badge>
              )}
            </div>

            <div className="whitespace-pre-wrap rounded-lg border border-border bg-muted/40 p-4 text-sm leading-relaxed text-foreground/90">
              {email.body_text?.trim() || email.snippet || "No content available."}
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
