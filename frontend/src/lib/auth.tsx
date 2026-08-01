"use client";

import { createContext, useContext, type ReactNode } from "react";
import { motion } from "framer-motion";
import { Mail } from "lucide-react";

import { ApiError, getCurrentUser, loginUrl } from "@/lib/api";
import { useAsync } from "@/hooks/use-async";
import type { UserProfile } from "@/lib/types";
import { Button } from "@/components/ui/button";

interface AuthContextValue {
  user: UserProfile;
  refetch: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

/** The authenticated user, from the nearest `AuthGate`. Always non-null: `AuthGate` never renders children until sign-in succeeds. */
export function useCurrentUser(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useCurrentUser must be used within <AuthGate>.");
  }
  return ctx;
}

/**
 * Gates the whole dashboard behind a real session check against
 * `GET /auth/me`. Three states: checking (skeleton), signed out (sign-in
 * screen linking to the real Google OAuth flow), signed in (renders
 * children with the user available via `useCurrentUser`).
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const { data, error, isLoading, refetch } = useAsync(getCurrentUser);

  if (isLoading) {
    return (
      <div className="flex h-dvh items-center justify-center bg-background">
        <motion.div
          animate={{ opacity: [0.4, 1, 0.4] }}
          transition={{ duration: 1.6, repeat: Infinity, ease: "easeInOut" }}
          className="flex items-center gap-2 text-muted-foreground"
        >
          <Mail className="h-5 w-5" />
          <span className="text-sm">Checking your session…</span>
        </motion.div>
      </div>
    );
  }

  if (error || !data) {
    const isUnauthorized = error instanceof ApiError && error.status === 401;
    return <SignInScreen isConnectionError={!isUnauthorized} />;
  }

  return (
    <AuthContext.Provider value={{ user: data, refetch }}>{children}</AuthContext.Provider>
  );
}

function SignInScreen({ isConnectionError }: { isConnectionError: boolean }) {
  return (
    <div className="flex h-dvh items-center justify-center bg-background px-6">
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
        className="flex w-full max-w-sm flex-col items-center gap-6 text-center"
      >
        <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-primary text-primary-foreground shadow-lg shadow-primary/20">
          <Mail className="h-7 w-7" />
        </div>
        <div className="space-y-1.5">
          <h1 className="text-xl font-semibold tracking-tight">
            AI Executive Email Assistant
          </h1>
          <p className="text-sm text-muted-foreground">
            {isConnectionError
              ? "Couldn't reach the API. Make sure the backend is running, then try again."
              : "Sign in with Google to see your inbox, tasks, and drafts."}
          </p>
        </div>
        <Button
          size="lg"
          className="w-full"
          render={<a href={loginUrl()}>Sign in with Google</a>}
        />
      </motion.div>
    </div>
  );
}
