import { describe, it, expect, vi, beforeEach } from "vitest";
import { apiClient, ApiClientError } from "../api/client";

describe("ApiClient REST Wrapper", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("successfully performs GET request and parses JSON", async () => {
    const mockHealth = {
      status: "ok",
      version: "0.1.0",
      app_name: "RedCell_OS",
      timestamp_utc: new Date().toISOString(),
      environment: "development",
    };

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => mockHealth,
    });

    const result = await apiClient.getHealth();
    expect(result.status).toBe("ok");
    expect(result.version).toBe("0.1.0");
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/health"),
      expect.objectContaining({ method: "GET" })
    );
  });

  it("throws ApiClientError with status and detail on HTTP failure", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      statusText: "Not Found",
      json: async () => ({ detail: "Engagement eng-999 not found" }),
    });

    try {
      await apiClient.get("/api/v1/engagements/eng-999");
      expect.unreachable("Should have thrown ApiClientError");
    } catch (err: unknown) {
      expect(err).toBeInstanceOf(ApiClientError);
      const apiErr = err as ApiClientError;
      expect(apiErr.status).toBe(404);
      expect(apiErr.message).toBe("Engagement eng-999 not found");
    }
  });

  it("handles network failure and abort timeouts cleanly", async () => {
    const abortErr = new Error("The operation was aborted");
    abortErr.name = "AbortError";
    global.fetch = vi.fn().mockRejectedValue(abortErr);

    try {
      await apiClient.get("/health", { timeoutMs: 50 });
      expect.unreachable("Should have thrown ApiClientError");
    } catch (err: unknown) {
      expect(err).toBeInstanceOf(ApiClientError);
      const apiErr = err as ApiClientError;
      expect(apiErr.status).toBe(408);
      expect(apiErr.message).toContain("timed out");
    }
  });
});
