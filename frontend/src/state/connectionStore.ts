import { create } from "zustand";
import { config } from "../config";

export type ConnectionStatus =
  | "CONNECTING"
  | "CONNECTED"
  | "DEGRADED"
  | "DISCONNECTED"
  | "FAILED";

export interface HealthData {
  status: string;
  version: string;
  app_name: string;
  timestamp_utc: string;
  environment: string;
}

export interface ConnectionStoreState {
  status: ConnectionStatus;
  latencyMs: number | null;
  backendVersion: string | null;
  appName: string | null;
  environment: string | null;
  lastCheckedAt: string | null;
  consecutiveFailures: number;
  pollingIntervalMs: number;
  errorMessage: string | null;
  isPollingActive: boolean;

  // Actions
  setStatus: (status: ConnectionStatus) => void;
  checkHealth: (baseUrl?: string) => Promise<ConnectionStatus>;
  startPolling: (intervalMs?: number, baseUrl?: string) => () => void;
  stopPolling: () => void;
  reset: () => void;
}

const DEFAULT_POLL_INTERVAL_MS = 2000;
const MAX_BACKOFF_POLL_INTERVAL_MS = 6000;
const DEGRADED_LATENCY_THRESHOLD_MS = 1200;
const FAILED_FAILURE_THRESHOLD = 5;

let pollingTimer: ReturnType<typeof setTimeout> | null = null;

export const useConnectionStore = create<ConnectionStoreState>((set, get) => ({
  status: "CONNECTING",
  latencyMs: null,
  backendVersion: null,
  appName: null,
  environment: null,
  lastCheckedAt: null,
  consecutiveFailures: 0,
  pollingIntervalMs: DEFAULT_POLL_INTERVAL_MS,
  errorMessage: null,
  isPollingActive: false,

  setStatus: (status) => set({ status }),

  checkHealth: async (baseUrl) => {
    const apiBase = baseUrl || config.apiUrl;
    const startTime = performance.now();

    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 2500);

      const response = await fetch(`${apiBase}/health`, {
        signal: controller.signal,
        headers: { Accept: "application/json" },
      });
      clearTimeout(timeoutId);

      const latency = Math.round(performance.now() - startTime);

      if (response.ok) {
        const data: HealthData = await response.json();
        const nextStatus: ConnectionStatus =
          latency > DEGRADED_LATENCY_THRESHOLD_MS ? "DEGRADED" : "CONNECTED";

        set({
          status: nextStatus,
          latencyMs: latency,
          backendVersion: data.version,
          appName: data.app_name,
          environment: data.environment,
          lastCheckedAt: new Date().toISOString(),
          consecutiveFailures: 0,
          pollingIntervalMs: DEFAULT_POLL_INTERVAL_MS,
          errorMessage: null,
        });

        return nextStatus;
      } else {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
    } catch (err: unknown) {
      const errorMsg = err instanceof Error ? err.message : "Connection failed";
      const failures = get().consecutiveFailures + 1;
      const nextStatus: ConnectionStatus =
        failures >= FAILED_FAILURE_THRESHOLD ? "FAILED" : "DISCONNECTED";

      const backoffInterval = Math.min(
        DEFAULT_POLL_INTERVAL_MS * Math.pow(1.5, failures),
        MAX_BACKOFF_POLL_INTERVAL_MS
      );

      set({
        status: nextStatus,
        latencyMs: null,
        lastCheckedAt: new Date().toISOString(),
        consecutiveFailures: failures,
        pollingIntervalMs: backoffInterval,
        errorMessage: errorMsg,
      });

      return nextStatus;
    }
  },

  startPolling: (intervalMs = DEFAULT_POLL_INTERVAL_MS, baseUrl) => {
    if (pollingTimer) {
      clearTimeout(pollingTimer);
    }

    set({ isPollingActive: true, pollingIntervalMs: intervalMs });

    const poll = async () => {
      if (!get().isPollingActive) return;
      await get().checkHealth(baseUrl);
      const nextInterval = get().pollingIntervalMs;
      pollingTimer = setTimeout(poll, nextInterval);
    };

    poll();

    return () => {
      get().stopPolling();
    };
  },

  stopPolling: () => {
    if (pollingTimer) {
      clearTimeout(pollingTimer);
      pollingTimer = null;
    }
    set({ isPollingActive: false });
  },

  reset: () => {
    if (pollingTimer) {
      clearTimeout(pollingTimer);
      pollingTimer = null;
    }
    set({
      status: "CONNECTING",
      latencyMs: null,
      backendVersion: null,
      appName: null,
      environment: null,
      lastCheckedAt: null,
      consecutiveFailures: 0,
      pollingIntervalMs: DEFAULT_POLL_INTERVAL_MS,
      errorMessage: null,
      isPollingActive: false,
    });
  },
}));
