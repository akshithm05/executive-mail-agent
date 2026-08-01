"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { format } from "date-fns";
import { Check, Pencil, Sparkles, X } from "lucide-react";

import { Card, CardContent, CardFooter, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  approveDraftReply,
  discardDraftReply,
  editDraftReply,
  regenerateDraftReply,
} from "@/lib/api";
import { DRAFT_REPLY_TONES, type DraftReply, type DraftReplyTone } from "@/lib/types";

const STATUS_VARIANT: Record<DraftReply["status"], "default" | "secondary" | "outline" | "destructive"> = {
  draft: "outline",
  pending_review: "secondary",
  approved: "default",
  sent: "secondary",
  discarded: "destructive",
};

const TONE_LABEL: Record<DraftReplyTone, string> = {
  professional: "Professional",
  friendly: "Friendly",
  formal: "Formal",
  executive: "Executive",
  short: "Short",
  detailed: "Detailed",
  apology: "Apology",
  thank_you: "Thank you",
  follow_up: "Follow up",
  negotiation: "Negotiation",
  clarification: "Clarification",
};

interface DraftCardProps {
  draft: DraftReply;
  index?: number;
  onChanged: () => void;
}

export function DraftCard({ draft, index = 0, onChanged }: DraftCardProps) {
  const [editOpen, setEditOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const isDecided = draft.status === "approved" || draft.status === "discarded" || draft.status === "sent";

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    try {
      await action();
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: Math.min(index * 0.04, 0.3) }}
    >
      <Card>
        <CardHeader className="flex-row items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold">{draft.subject || "(no subject)"}</p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {format(new Date(draft.updated_at), "PPP p")}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            {draft.tone && <Badge variant="secondary">{TONE_LABEL[draft.tone]}</Badge>}
            <Badge variant={STATUS_VARIANT[draft.status]} className="capitalize">
              {draft.status.replace("_", " ")}
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-2">
          <p className="line-clamp-3 whitespace-pre-wrap text-sm text-foreground/80">
            {draft.body_text}
          </p>
          {draft.reasoning && (
            <p className="text-xs italic text-muted-foreground">“{draft.reasoning}”</p>
          )}
          {draft.confidence !== null && (
            <p className="text-xs text-muted-foreground">
              Confidence {Math.round(draft.confidence * 100)}%
            </p>
          )}
        </CardContent>
        <CardFooter className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" onClick={() => setEditOpen(true)}>
            <Pencil className="h-3.5 w-3.5" /> Edit
          </Button>

          <RegeneratePopover
            disabled={busy}
            onRegenerate={(tone) => run(() => regenerateDraftReply(draft.id, tone))}
          />

          {!isDecided && (
            <>
              <Button
                size="sm"
                variant="outline"
                disabled={busy}
                onClick={() => run(() => approveDraftReply(draft.id))}
              >
                <Check className="h-3.5 w-3.5" /> Approve
              </Button>
              <Button
                size="sm"
                variant="ghost"
                disabled={busy}
                className="text-destructive hover:text-destructive"
                onClick={() => run(() => discardDraftReply(draft.id))}
              >
                <X className="h-3.5 w-3.5" /> Discard
              </Button>
            </>
          )}
        </CardFooter>
      </Card>

      <EditDraftDialog
        draft={draft}
        open={editOpen}
        onOpenChange={setEditOpen}
        onSaved={onChanged}
      />
    </motion.div>
  );
}

function RegeneratePopover({
  disabled,
  onRegenerate,
}: {
  disabled: boolean;
  onRegenerate: (tone?: DraftReplyTone) => void;
}) {
  const [open, setOpen] = useState(false);
  const [tone, setTone] = useState<DraftReplyTone | "auto">("auto");

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        disabled={disabled}
        className={buttonVariants({ size: "sm", variant: "outline" })}
      >
        <Sparkles className="h-3.5 w-3.5" /> Regenerate
      </PopoverTrigger>
      <PopoverContent className="w-64 space-y-3">
        <p className="text-xs font-medium text-muted-foreground">Tone</p>
        <Select value={tone} onValueChange={(v) => v && setTone(v as typeof tone)}>
          <SelectTrigger className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="auto">Let AI choose</SelectItem>
            {DRAFT_REPLY_TONES.map((t) => (
              <SelectItem key={t} value={t}>
                {TONE_LABEL[t]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button
          size="sm"
          className="w-full"
          onClick={() => {
            onRegenerate(tone === "auto" ? undefined : tone);
            setOpen(false);
          }}
        >
          Regenerate draft
        </Button>
      </PopoverContent>
    </Popover>
  );
}

function EditDraftDialog({
  draft,
  open,
  onOpenChange,
  onSaved,
}: {
  draft: DraftReply;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: () => void;
}) {
  const [subject, setSubject] = useState(draft.subject);
  const [body, setBody] = useState(draft.body_text);
  const [saving, setSaving] = useState(false);

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (next) {
          setSubject(draft.subject);
          setBody(draft.body_text);
        }
        onOpenChange(next);
      }}
    >
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Edit draft</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">Subject</label>
            <Input value={subject} onChange={(e) => setSubject(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">Body</label>
            <Textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              rows={10}
            />
          </div>
        </div>
        <DialogFooter>
          <Button
            disabled={saving}
            onClick={async () => {
              setSaving(true);
              try {
                await editDraftReply(draft.id, { subject, body_text: body });
                onSaved();
                onOpenChange(false);
              } finally {
                setSaving(false);
              }
            }}
          >
            Save changes
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
