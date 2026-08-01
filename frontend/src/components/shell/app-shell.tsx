"use client";

import { useState, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import { Menu, Mail } from "lucide-react";
import { motion } from "framer-motion";

import { AuthGate, useCurrentUser } from "@/lib/auth";
import { useAsync } from "@/hooks/use-async";
import { getDashboardSummary, logout } from "@/lib/api";
import { NavLinks } from "@/components/shell/nav-links";
import { ThemeToggle } from "@/components/shell/theme-toggle";
import { buttonVariants } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import {
  Avatar,
  AvatarFallback,
  AvatarImage,
} from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <AuthGate>
      <ShellChrome>{children}</ShellChrome>
    </AuthGate>
  );
}

function ShellChrome({ children }: { children: ReactNode }) {
  const { user } = useCurrentUser();
  const { data: summary } = useAsync(getDashboardSummary, []);
  const [mobileOpen, setMobileOpen] = useState(false);
  const pathname = usePathname();

  const initials = user.display_name
    .split(" ")
    .map((part) => part[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();

  return (
    <div className="flex min-h-dvh w-full bg-background">
      {/* Desktop sidebar */}
      <aside className="hidden w-64 shrink-0 border-r border-sidebar-border bg-sidebar md:flex md:flex-col">
        <div className="flex h-16 items-center gap-2 px-5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <Mail className="h-4 w-4" />
          </div>
          <span className="text-sm font-semibold tracking-tight">Executive Mail</span>
        </div>
        <div className="flex-1 overflow-y-auto px-3 py-2">
          <NavLinks
            unreadNotifications={summary?.unread_notifications}
            urgentEmails={summary?.urgent_emails}
          />
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Topbar */}
        <header className="sticky top-0 z-20 flex h-16 items-center gap-3 border-b border-border bg-background/80 px-4 backdrop-blur supports-backdrop-filter:bg-background/60 md:px-6">
          <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
            <SheetTrigger
              aria-label="Open navigation"
              className={buttonVariants({
                variant: "ghost",
                size: "icon",
                className: "md:hidden",
              })}
            >
              <Menu className="h-5 w-5" />
            </SheetTrigger>
            <SheetContent side="left" className="w-64 bg-sidebar p-0">
              <SheetTitle className="sr-only">Navigation</SheetTitle>
              <div className="flex h-16 items-center gap-2 px-5">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
                  <Mail className="h-4 w-4" />
                </div>
                <span className="text-sm font-semibold tracking-tight">
                  Executive Mail
                </span>
              </div>
              <div className="px-3 py-2">
                <NavLinks
                  onNavigate={() => setMobileOpen(false)}
                  unreadNotifications={summary?.unread_notifications}
                  urgentEmails={summary?.urgent_emails}
                />
              </div>
            </SheetContent>
          </Sheet>

          <div className="flex-1" />

          <ThemeToggle />

          <DropdownMenu>
            <DropdownMenuTrigger className="rounded-full outline-none ring-primary/40 focus-visible:ring-2">
              <Avatar className="h-8 w-8">
                <AvatarImage src={user.picture_url} alt={user.display_name} />
                <AvatarFallback>{initials || "U"}</AvatarFallback>
              </Avatar>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              <DropdownMenuLabel className="flex flex-col">
                <span className="text-sm font-medium">{user.display_name}</span>
                <span className="text-xs font-normal text-muted-foreground">
                  {user.email}
                </span>
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                variant="destructive"
                onSelect={() => {
                  void logout().then(() => window.location.assign("/"));
                }}
              >
                Sign out
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </header>

        <motion.main
          key={pathname}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
          className="flex-1 px-4 py-6 md:px-8 md:py-8"
        >
          {children}
        </motion.main>
      </div>
    </div>
  );
}
