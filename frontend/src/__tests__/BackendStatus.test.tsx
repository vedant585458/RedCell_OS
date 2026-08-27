import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { BackendStatus } from "../components/BackendStatus";
import { useConnectionStore } from "../state/connectionStore";

describe("BackendStatus UI Component", () => {
  beforeEach(() => {
    useConnectionStore.getState().reset();
  });

  it("renders Connecting badge initially", () => {
    render(<BackendStatus />);
    expect(screen.getByText(/Connecting\.\.\./i)).toBeDefined();
  });

  it("renders Online badge when state is CONNECTED", () => {
    useConnectionStore.setState({
      status: "CONNECTED",
      latencyMs: 12,
      backendVersion: "0.1.0",
    });

    render(<BackendStatus />);
    expect(screen.getByText(/Backend Online/i)).toBeDefined();
    expect(screen.getByText("12ms")).toBeDefined();
    expect(screen.getByText("v0.1.0")).toBeDefined();
  });

  it("renders Disconnected badge and retry button on DISCONNECTED", () => {
    useConnectionStore.setState({
      status: "DISCONNECTED",
      consecutiveFailures: 2,
    });

    render(<BackendStatus />);
    expect(screen.getByText(/Disconnected/i)).toBeDefined();
    expect(screen.getByText(/Retry \(2\)/i)).toBeDefined();
  });

  it("renders Circuit Tripped / Failed badge on FAILED state", () => {
    useConnectionStore.setState({
      status: "FAILED",
      consecutiveFailures: 5,
    });

    render(<BackendStatus />);
    expect(screen.getByText(/Backend Offline \(Circuit Tripped\)/i)).toBeDefined();
  });
});
