import { describe, it, expect, beforeEach, vi } from "vitest";
import { useConnectionStore } from "../state/connectionStore";

describe("useConnectionStore Finite-State Machine", () => {
  beforeEach(() => {
    useConnectionStore.getState().reset();
    vi.restoreAllMocks();
  });

  it("should initialize with CONNECTING state", () => {
    const state = useConnectionStore.getState();
    expect(state.status).toBe("CONNECTING");
    expect(state.backendVersion).toBeNull();
    expect(state.consecutiveFailures).toBe(0);
  });

  it("should transition to CONNECTED on successful 200 OK health response", async () => {
    const mockHealthData = {
      status: "ok",
      version: "0.1.0",
      app_name: "RedCell_OS",
      timestamp_utc: new Date().toISOString(),
      environment: "development",
    };

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => mockHealthData,
    });

    const status = await useConnectionStore.getState().checkHealth("http://127.0.0.1:8000");

    expect(status).toBe("CONNECTED");
    const state = useConnectionStore.getState();
    expect(state.status).toBe("CONNECTED");
    expect(state.backendVersion).toBe("0.1.0");
    expect(state.appName).toBe("RedCell_OS");
    expect(state.consecutiveFailures).toBe(0);
    expect(state.errorMessage).toBeNull();
  });

  it("should transition to DISCONNECTED on initial network error", async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error("Failed to fetch"));

    const status = await useConnectionStore.getState().checkHealth("http://127.0.0.1:8000");

    expect(status).toBe("DISCONNECTED");
    const state = useConnectionStore.getState();
    expect(state.status).toBe("DISCONNECTED");
    expect(state.consecutiveFailures).toBe(1);
    expect(state.errorMessage).toBe("Failed to fetch");
  });

  it("should transition to FAILED after 5 consecutive failures", async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error("Connection refused"));

    for (let i = 1; i <= 4; i++) {
      await useConnectionStore.getState().checkHealth("http://127.0.0.1:8000");
      expect(useConnectionStore.getState().status).toBe("DISCONNECTED");
      expect(useConnectionStore.getState().consecutiveFailures).toBe(i);
    }

    // 5th failure should trigger FAILED
    const finalStatus = await useConnectionStore.getState().checkHealth("http://127.0.0.1:8000");
    expect(finalStatus).toBe("FAILED");
    const state = useConnectionStore.getState();
    expect(state.status).toBe("FAILED");
    expect(state.consecutiveFailures).toBe(5);
  });

  it("should recover from FAILED to CONNECTED on successful response", async () => {
    // Force FAILED state
    global.fetch = vi.fn().mockRejectedValue(new Error("Connection refused"));
    for (let i = 0; i < 5; i++) {
      await useConnectionStore.getState().checkHealth("http://127.0.0.1:8000");
    }
    expect(useConnectionStore.getState().status).toBe("FAILED");

    // Successful mock
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        status: "ok",
        version: "0.1.0",
        app_name: "RedCell_OS",
        timestamp_utc: new Date().toISOString(),
        environment: "development",
      }),
    });

    const recoveredStatus = await useConnectionStore.getState().checkHealth("http://127.0.0.1:8000");
    expect(recoveredStatus).toBe("CONNECTED");
    expect(useConnectionStore.getState().consecutiveFailures).toBe(0);
  });
});
