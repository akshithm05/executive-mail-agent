import { render, screen } from "@testing-library/react";
import { Inbox } from "lucide-react";
import { describe, expect, it, vi } from "vitest";

import { EmptyState, ErrorState } from "@/components/shared/empty-state";

describe("EmptyState", () => {
  it("renders the title and, when given, the description", () => {
    render(<EmptyState icon={Inbox} title="No emails yet" description="Check back later." />);
    expect(screen.getByText("No emails yet")).toBeInTheDocument();
    expect(screen.getByText("Check back later.")).toBeInTheDocument();
  });

  it("omits the description paragraph when none is given", () => {
    render(<EmptyState icon={Inbox} title="No emails yet" />);
    expect(screen.getByText("No emails yet")).toBeInTheDocument();
    expect(screen.queryByText("Check back later.")).not.toBeInTheDocument();
  });
});

describe("ErrorState", () => {
  it("shows a default message when none is given", () => {
    render(<ErrorState />);
    expect(screen.getByText("Something went wrong.")).toBeInTheDocument();
  });

  it("shows a custom message when given", () => {
    render(<ErrorState message="Couldn't load your inbox." />);
    expect(screen.getByText("Couldn't load your inbox.")).toBeInTheDocument();
  });

  it("only renders the retry button when onRetry is provided, and calls it on click", async () => {
    const { rerender } = render(<ErrorState />);
    expect(screen.queryByRole("button", { name: /try again/i })).not.toBeInTheDocument();

    const onRetry = vi.fn();
    rerender(<ErrorState onRetry={onRetry} />);
    const button = screen.getByRole("button", { name: /try again/i });
    button.click();
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
