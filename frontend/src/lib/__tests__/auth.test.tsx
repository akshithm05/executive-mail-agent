import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, loginUrl } from "@/lib/api";
import { AuthGate, useCurrentUser } from "@/lib/auth";
import type { UserProfile } from "@/lib/types";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    getCurrentUser: vi.fn(),
  };
});

const { getCurrentUser } = await import("@/lib/api");
const getCurrentUserMock = vi.mocked(getCurrentUser);

const USER: UserProfile = {
  id: "u1",
  tenant_id: "t1",
  email: "exec@example.com",
  display_name: "Executive User",
  picture_url: "",
};

function ProtectedContent() {
  const { user } = useCurrentUser();
  return <div>Welcome, {user.email}</div>;
}

describe("AuthGate", () => {
  afterEach(() => {
    getCurrentUserMock.mockReset();
  });

  it("shows a checking-session state while the request is in flight", () => {
    getCurrentUserMock.mockReturnValue(new Promise(() => {}));
    render(
      <AuthGate>
        <ProtectedContent />
      </AuthGate>,
    );
    expect(screen.getByText(/checking your session/i)).toBeInTheDocument();
  });

  it("renders children with the user available via useCurrentUser once signed in", async () => {
    getCurrentUserMock.mockResolvedValue(USER);
    render(
      <AuthGate>
        <ProtectedContent />
      </AuthGate>,
    );
    await waitFor(() =>
      expect(screen.getByText("Welcome, exec@example.com")).toBeInTheDocument(),
    );
  });

  it("shows a sign-in screen (linking to Google OAuth) on a 401", async () => {
    getCurrentUserMock.mockRejectedValue(
      new ApiError({ title: "Unauthorized", status: 401, code: "unauthorized", detail: "" }),
    );
    render(
      <AuthGate>
        <ProtectedContent />
      </AuthGate>,
    );
    const link = await screen.findByRole("link", { name: /sign in with google/i });
    expect(link).toHaveAttribute("href", loginUrl());
  });

  it("shows a connection-error message (not a sign-in prompt) on a non-401 failure", async () => {
    getCurrentUserMock.mockRejectedValue(new Error("Failed to fetch"));
    render(
      <AuthGate>
        <ProtectedContent />
      </AuthGate>,
    );
    await waitFor(() =>
      expect(screen.getByText(/couldn't reach the api/i)).toBeInTheDocument(),
    );
  });

  it("useCurrentUser throws when used outside an AuthGate", () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<ProtectedContent />)).toThrow(
      "useCurrentUser must be used within <AuthGate>.",
    );
    consoleError.mockRestore();
  });
});
