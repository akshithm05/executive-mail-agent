"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { motion } from "framer-motion";

import { cn } from "@/lib/utils";
import { NAV_ITEMS } from "@/components/shell/nav-items";
import { Badge } from "@/components/ui/badge";

interface NavLinksProps {
  onNavigate?: () => void;
  unreadNotifications?: number;
  urgentEmails?: number;
}

export function NavLinks({ onNavigate, unreadNotifications, urgentEmails }: NavLinksProps) {
  const pathname = usePathname();

  return (
    <nav className="flex flex-col gap-1">
      {NAV_ITEMS.map((item) => {
        const isActive = pathname === item.href;
        const badgeCount =
          item.href === "/notifications"
            ? unreadNotifications
            : item.href === "/inbox"
              ? urgentEmails
              : undefined;

        return (
          <Link
            key={item.href}
            href={item.href}
            onClick={onNavigate}
            className={cn(
              "relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
              isActive
                ? "text-sidebar-primary-foreground"
                : "text-sidebar-foreground/70 hover:bg-sidebar-accent hover:text-sidebar-foreground",
            )}
          >
            {isActive && (
              <motion.div
                layoutId="active-nav-pill"
                className="absolute inset-0 rounded-lg bg-sidebar-primary"
                transition={{ type: "spring", stiffness: 500, damping: 40 }}
              />
            )}
            <item.icon className="relative z-10 h-4 w-4 shrink-0" />
            <span className="relative z-10 flex-1">{item.label}</span>
            {!!badgeCount && (
              <Badge
                variant={isActive ? "secondary" : "default"}
                className="relative z-10 h-5 min-w-5 justify-center rounded-full px-1 text-[10px] tabular-nums"
              >
                {badgeCount > 99 ? "99+" : badgeCount}
              </Badge>
            )}
          </Link>
        );
      })}
    </nav>
  );
}
