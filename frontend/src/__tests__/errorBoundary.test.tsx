import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import React from "react";
import { ErrorBoundary } from "../components/ErrorBoundary";

// A dummy component that throws an error when triggerError=true
const ProblemChild: React.FC<{ shouldThrow?: boolean }> = ({ shouldThrow = false }) => {
  if (shouldThrow) {
    throw new Error("Simulated intentional rendering failure");
  }
  return <div>Everything is fine in the office simulation.</div>;
};

describe("ErrorBoundary Component", () => {
  beforeEach(() => {
    // Suppress console.error in tests when error boundary catches
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  it("renders children normally when no error occurs", () => {
    render(
      <ErrorBoundary>
        <ProblemChild shouldThrow={false} />
      </ErrorBoundary>
    );

    expect(screen.getByText("Everything is fine in the office simulation.")).toBeDefined();
    expect(screen.queryByText(/Simulation Viewport Crashed/i)).toBeNull();
  });

  it("catches thrown error and renders error boundary fallback UI", () => {
    render(
      <ErrorBoundary>
        <ProblemChild shouldThrow={true} />
      </ErrorBoundary>
    );

    expect(screen.getByText(/Simulation Viewport Crashed/i)).toBeDefined();
    expect(screen.getByText(/Simulated intentional rendering failure/i)).toBeDefined();
    expect(screen.getByText(/Command Center/i)).toBeDefined();
    expect(screen.getByText(/Try Recover View/i)).toBeDefined();
  });

  it("toggles diagnostic stack trace when clicking details button", () => {
    render(
      <ErrorBoundary>
        <ProblemChild shouldThrow={true} />
      </ErrorBoundary>
    );

    const toggleBtn = screen.getByText(/Show Diagnostic Stack Trace/i);
    fireEvent.click(toggleBtn);
    expect(screen.getByText(/Hide Stack Trace/i)).toBeDefined();
  });

  it("calls onReset callback when 'Try Recover View' is clicked", () => {
    const handleReset = vi.fn();
    render(
      <ErrorBoundary onReset={handleReset}>
        <ProblemChild shouldThrow={true} />
      </ErrorBoundary>
    );

    const recoverBtn = screen.getByText(/Try Recover View/i);
    fireEvent.click(recoverBtn);
    expect(handleReset).toHaveBeenCalledTimes(1);
  });
});
