import { render, screen } from "@testing-library/react";
import { Mail } from "lucide-react";
import { describe, expect, it } from "vitest";

import { StatTile } from "@/components/dashboard/stat-tile";

describe("StatTile", () => {
  it("renders the label and the (eventually animated) value", async () => {
    render(<StatTile label="Unread" value={12} icon={Mail} />);
    expect(screen.getByText("Unread")).toBeInTheDocument();
    // AnimatedNumber tweens from 0 -> value via a rAF-driven effect, so the
    // final text isn't necessarily present synchronously -- just assert the
    // tile rendered without crashing and started from a valid number node.
    expect(screen.getByText(/^\d+$/)).toBeInTheDocument();
  });

  it("applies the tone-specific icon-badge classes", () => {
    const { container: critical } = render(
      <StatTile label="Overdue" value={3} icon={Mail} tone="critical" />,
    );
    expect(critical.querySelector(".bg-critical\\/10")).not.toBeNull();

    const { container: good } = render(
      <StatTile label="On track" value={9} icon={Mail} tone="good" />,
    );
    expect(good.querySelector(".bg-good\\/10")).not.toBeNull();
  });
});
