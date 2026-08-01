"use client";

import { useEffect, useState } from "react";
import { useTheme } from "next-themes";
import { motion } from "framer-motion";
import { LogOut, Monitor, Moon, Sun } from "lucide-react";

import { useAsync } from "@/hooks/use-async";
import { listPreferences, logout, setPreference } from "@/lib/api";
import { useCurrentUser } from "@/lib/auth";
import { DRAFT_REPLY_TONES } from "@/lib/types";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

const TONE_LABEL: Record<string, string> = {
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

function boolOf(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

export default function SettingsPage() {
  const { user } = useCurrentUser();
  const { theme, setTheme } = useTheme();
  const { data: preferences, isLoading, refetch } = useAsync(listPreferences, []);

  const [notifyUrgent, setNotifyUrgent] = useState(true);
  const [notifyDeadline, setNotifyDeadline] = useState(true);
  const [defaultTone, setDefaultTone] = useState("professional");

  // Synchronizes locally-editable toggle/select state from the fetched
  // preferences whenever they (re)load -- a standard "derive local state
  // from a prop" effect, not a cascading-render risk.
  useEffect(() => {
    if (!preferences) return;
    const urgent = preferences.find((p) => p.key === "notify_on_urgent");
    const deadline = preferences.find((p) => p.key === "notify_on_deadline");
    const tone = preferences.find((p) => p.key === "default_reply_tone");
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (urgent) setNotifyUrgent(boolOf(urgent.value.enabled, true));
    if (deadline) setNotifyDeadline(boolOf(deadline.value.enabled, true));
    if (tone && typeof tone.value.tone === "string") setDefaultTone(tone.value.tone);
  }, [preferences]);

  const initials = user.display_name
    .split(" ")
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
        <p className="text-sm text-muted-foreground">
          Appearance, notification, and draft-reply preferences.
        </p>
      </div>

      <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }}>
        <Card>
          <CardHeader>
            <CardTitle>Account</CardTitle>
          </CardHeader>
          <CardContent className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <Avatar className="h-11 w-11">
                <AvatarImage src={user.picture_url} alt={user.display_name} />
                <AvatarFallback>{initials || "U"}</AvatarFallback>
              </Avatar>
              <div>
                <p className="text-sm font-medium">{user.display_name}</p>
                <p className="text-xs text-muted-foreground">{user.email}</p>
              </div>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => void logout().then(() => window.location.assign("/"))}
            >
              <LogOut className="h-3.5 w-3.5" /> Sign out
            </Button>
          </CardContent>
        </Card>
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, delay: 0.05 }}
      >
        <Card>
          <CardHeader>
            <CardTitle>Appearance</CardTitle>
            <CardDescription>Choose how Executive Mail looks on this device.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-3 gap-2">
              {(
                [
                  { value: "light", label: "Light", icon: Sun },
                  { value: "dark", label: "Dark", icon: Moon },
                  { value: "system", label: "System", icon: Monitor },
                ] as const
              ).map((option) => (
                <button
                  key={option.value}
                  onClick={() => setTheme(option.value)}
                  className={cn(
                    "flex flex-col items-center gap-2 rounded-lg border px-3 py-3 text-xs font-medium transition-colors",
                    theme === option.value
                      ? "border-primary bg-primary/5 text-primary"
                      : "border-border text-muted-foreground hover:bg-accent",
                  )}
                >
                  <option.icon className="h-4 w-4" />
                  {option.label}
                </button>
              ))}
            </div>
          </CardContent>
        </Card>
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, delay: 0.1 }}
      >
        <Card>
          <CardHeader>
            <CardTitle>Notifications</CardTitle>
            <CardDescription>Choose what generates an in-app notification.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {isLoading ? (
              <>
                <Skeleton className="h-6 w-full" />
                <Skeleton className="h-6 w-full" />
              </>
            ) : (
              <>
                <div className="flex items-center justify-between">
                  <Label htmlFor="notify-urgent" className="font-normal">
                    Urgent emails
                  </Label>
                  <Switch
                    id="notify-urgent"
                    checked={notifyUrgent}
                    onCheckedChange={async (checked) => {
                      setNotifyUrgent(checked);
                      await setPreference(
                        "notify_on_urgent",
                        { enabled: checked },
                        "notifications",
                      );
                      refetch();
                    }}
                  />
                </div>
                <div className="flex items-center justify-between">
                  <Label htmlFor="notify-deadline" className="font-normal">
                    Upcoming deadlines
                  </Label>
                  <Switch
                    id="notify-deadline"
                    checked={notifyDeadline}
                    onCheckedChange={async (checked) => {
                      setNotifyDeadline(checked);
                      await setPreference(
                        "notify_on_deadline",
                        { enabled: checked },
                        "notifications",
                      );
                      refetch();
                    }}
                  />
                </div>
              </>
            )}
          </CardContent>
        </Card>
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, delay: 0.15 }}
      >
        <Card>
          <CardHeader>
            <CardTitle>Draft replies</CardTitle>
            <CardDescription>
              The default tone used when the AI drafts a reply, unless the email calls for
              something else.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Select
              value={defaultTone}
              onValueChange={async (value) => {
                if (!value) return;
                setDefaultTone(value);
                await setPreference("default_reply_tone", { tone: value }, "drafting");
                refetch();
              }}
            >
              <SelectTrigger className="w-56">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {DRAFT_REPLY_TONES.map((tone) => (
                  <SelectItem key={tone} value={tone}>
                    {TONE_LABEL[tone]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </CardContent>
        </Card>
      </motion.div>
    </div>
  );
}
