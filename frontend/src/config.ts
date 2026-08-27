/**
 * Typed Runtime Configuration for RedCell_OS Frontend
 * Sourced from Vite environment variables (VITE_*) at dev/build time.
 */

export interface FeatureFlags {
  enable2DCanvas: boolean;
  enableMockTarget: boolean;
  enableTerminalLogs: boolean;
  enablePocVerification: boolean;
}

export interface FrontendConfig {
  apiUrl: string;
  wsUrl: string;
  appVersion: string;
  environment: "development" | "staging" | "production" | "test";
  healthPollIntervalMs: number;
  featureFlags: FeatureFlags;
}

function resolveApiUrl(): string {
  const envUrl = typeof import.meta !== "undefined" ? import.meta.env?.VITE_API_URL : undefined;
  if (envUrl && envUrl.trim()) {
    return envUrl.trim().replace(/\/+$/, "");
  }
  // Default to localhost:8000
  return "http://127.0.0.1:8000";
}

function resolveWsUrl(apiUrl: string): string {
  const envWsUrl = typeof import.meta !== "undefined" ? import.meta.env?.VITE_WS_URL : undefined;
  if (envWsUrl && envWsUrl.trim()) {
    return envWsUrl.trim().replace(/\/+$/, "");
  }

  // Derive from API URL
  if (apiUrl.startsWith("https://")) {
    return apiUrl.replace("https://", "wss://");
  }
  return apiUrl.replace("http://", "ws://");
}

export function createConfig(overrides: Partial<FrontendConfig> = {}): FrontendConfig {
  const apiUrl = overrides.apiUrl || resolveApiUrl();
  const wsUrl = overrides.wsUrl || resolveWsUrl(apiUrl);

  const env = typeof import.meta !== "undefined" ? import.meta.env : undefined;

  return {
    apiUrl,
    wsUrl,
    appVersion: overrides.appVersion || env?.VITE_APP_VERSION || "0.1.0",
    environment:
      overrides.environment ||
      (env?.VITE_ENVIRONMENT as FrontendConfig["environment"]) ||
      "development",
    healthPollIntervalMs: overrides.healthPollIntervalMs || 2000,
    featureFlags: {
      enable2DCanvas:
        overrides.featureFlags?.enable2DCanvas ??
        (env?.VITE_ENABLE_2D_CANVAS !== "false"),
      enableMockTarget:
        overrides.featureFlags?.enableMockTarget ??
        (env?.VITE_ENABLE_MOCK_TARGET !== "false"),
      enableTerminalLogs:
        overrides.featureFlags?.enableTerminalLogs ??
        (env?.VITE_ENABLE_TERMINAL_LOGS !== "false"),
      enablePocVerification:
        overrides.featureFlags?.enablePocVerification ??
        (env?.VITE_ENABLE_POC_VERIFICATION !== "false"),
    },
  };
}

export const config = createConfig();

/**
 * Build a full API endpoint URL from a relative path.
 */
export function getApiUrl(path: string): string {
  const cleanPath = path.startsWith("/") ? path : `/${path}`;
  return `${config.apiUrl}${cleanPath}`;
}

/**
 * Build a full WebSocket endpoint URL with optional engagement ID and sequence parameter.
 */
export function getWebSocketUrl(engagementId?: string | null, lastSeenSeq: number = 0): string {
  const basePath = engagementId ? `/ws/engagements/${engagementId}` : "/ws/events";
  return `${config.wsUrl}${basePath}?last_seen_seq=${lastSeenSeq}`;
}

export default config;
