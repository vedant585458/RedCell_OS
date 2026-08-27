import { describe, it, expect } from "vitest";
import { createConfig, getApiUrl, getWebSocketUrl } from "../config";

describe("Frontend Runtime Configuration Module", () => {
  it("creates default configuration with fallback values", () => {
    const config = createConfig();

    expect(config.apiUrl).toBe("http://127.0.0.1:8000");
    expect(config.wsUrl).toBe("ws://127.0.0.1:8000");
    expect(config.appVersion).toBe("0.1.0");
    expect(config.environment).toBe("development");
    expect(config.healthPollIntervalMs).toBe(2000);
    expect(config.featureFlags.enable2DCanvas).toBe(true);
    expect(config.featureFlags.enableMockTarget).toBe(true);
  });

  it("applies configuration overrides correctly", () => {
    const customConfig = createConfig({
      apiUrl: "https://api.redcell.corp.internal:8443",
      environment: "production",
      healthPollIntervalMs: 5000,
      featureFlags: {
        enable2DCanvas: false,
        enableMockTarget: false,
        enableTerminalLogs: true,
        enablePocVerification: true,
      },
    });

    expect(customConfig.apiUrl).toBe("https://api.redcell.corp.internal:8443");
    expect(customConfig.wsUrl).toBe("wss://api.redcell.corp.internal:8443");
    expect(customConfig.environment).toBe("production");
    expect(customConfig.healthPollIntervalMs).toBe(5000);
    expect(customConfig.featureFlags.enable2DCanvas).toBe(false);
  });

  it("normalizes paths in getApiUrl", () => {
    expect(getApiUrl("/health")).toBe("http://127.0.0.1:8000/health");
    expect(getApiUrl("api/v1/engagements")).toBe("http://127.0.0.1:8000/api/v1/engagements");
  });

  it("generates correct WebSocket URL with query parameters", () => {
    const wsUrl = getWebSocketUrl("eng-mvp-001", 42);
    expect(wsUrl).toBe("ws://127.0.0.1:8000/ws/engagements/eng-mvp-001?last_seen_seq=42");

    const generalWsUrl = getWebSocketUrl(null, 0);
    expect(generalWsUrl).toBe("ws://127.0.0.1:8000/ws/events?last_seen_seq=0");
  });
});
