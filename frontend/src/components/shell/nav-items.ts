import type { LucideIcon } from "lucide-react";
import {
  Bell,
  CalendarDays,
  Inbox,
  LayoutGrid,
  ListTodo,
  Send,
  Settings,
} from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
}

export const NAV_ITEMS: NavItem[] = [
  { href: "/", label: "Overview", icon: LayoutGrid },
  { href: "/inbox", label: "Inbox", icon: Inbox },
  { href: "/tasks", label: "Tasks", icon: ListTodo },
  { href: "/calendar", label: "Calendar", icon: CalendarDays },
  { href: "/drafts", label: "Draft Replies", icon: Send },
  { href: "/notifications", label: "Notifications", icon: Bell },
  { href: "/settings", label: "Settings", icon: Settings },
];
