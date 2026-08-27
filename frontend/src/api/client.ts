/**
 * Global Typed REST API Client for RedCell_OS
 */

import { config } from "../config";

export class ApiClientError extends Error {
  public readonly status: number;
  public readonly url: string;
  public readonly data: unknown;
  public readonly timestamp: string;

  constructor(status: number, url: string, message: string, data?: unknown) {
    super(message);
    this.name = "ApiClientError";
    this.status = status;
    this.url = url;
    this.data = data;
    this.timestamp = new Date().toISOString();
    Object.setPrototypeOf(this, ApiClientError.prototype);
  }
}

export interface RequestOptions extends RequestInit {
  params?: Record<string, string | number | boolean | undefined | null>;
  timeoutMs?: number;
}

export interface HealthResponse {
  status: string;
  version: string;
  app_name: string;
  timestamp_utc: string;
  environment: string;
}

export interface EngagementSummary {
  engagement_id: string;
  status: string;
  organization: string;
  created_at: string;
  task_count: number;
  findings_count: number;
}

export interface ApprovalDecisionPayload {
  gate_id: string;
  decision: "GRANTED" | "REJECTED";
  reason?: string;
  operator_id: string;
}

export const API_BASE_URL = config.apiUrl;

class ApiClient {
  private baseUrl: string;

  constructor(baseUrl: string = API_BASE_URL) {
    this.baseUrl = baseUrl.replace(/\/+$/, "");
  }

  public setBaseUrl(url: string): void {
    this.baseUrl = url.replace(/\/+$/, "");
  }

  public getBaseUrl(): string {
    return this.baseUrl;
  }

  private buildUrl(path: string, params?: Record<string, string | number | boolean | undefined | null>): string {
    const cleanPath = path.startsWith("/") ? path : `/${path}`;
    const url = new URL(`${this.baseUrl}${cleanPath}`);

    if (params) {
      Object.entries(params).forEach(([key, value]) => {
        if (value !== undefined && value !== null) {
          url.searchParams.append(key, String(value));
        }
      });
    }

    return url.toString();
  }

  public async request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    const { params, timeoutMs = 10000, headers = {}, ...customConfig } = options;
    const url = this.buildUrl(path, params);

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);

    const configReq: RequestInit = {
      ...customConfig,
      signal: controller.signal,
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        ...headers,
      },
    };

    try {
      const response = await fetch(url, configReq);
      clearTimeout(timer);

      if (!response.ok) {
        let errorData: unknown = null;
        let errorMessage = `HTTP ${response.status}: ${response.statusText}`;

        try {
          errorData = await response.json();
          if (typeof errorData === "object" && errorData !== null && "detail" in errorData) {
            errorMessage = String((errorData as { detail: unknown }).detail);
          }
        } catch (_) {
          // Response was not JSON
        }

        throw new ApiClientError(response.status, url, errorMessage, errorData);
      }

      // Handle 204 No Content
      if (response.status === 204) {
        return {} as T;
      }

      return (await response.json()) as T;
    } catch (err: unknown) {
      clearTimeout(timer);
      if (err instanceof ApiClientError) {
        throw err;
      }
      if (err instanceof Error && err.name === "AbortError") {
        throw new ApiClientError(408, url, `Request timed out after ${timeoutMs}ms`);
      }
      const message = err instanceof Error ? err.message : "Network request failed";
      throw new ApiClientError(0, url, message);
    }
  }

  public get<T>(path: string, options?: RequestOptions): Promise<T> {
    return this.request<T>(path, { ...options, method: "GET" });
  }

  public post<T>(path: string, body?: unknown, options?: RequestOptions): Promise<T> {
    return this.request<T>(path, {
      ...options,
      method: "POST",
      body: body ? JSON.stringify(body) : undefined,
    });
  }

  public put<T>(path: string, body?: unknown, options?: RequestOptions): Promise<T> {
    return this.request<T>(path, {
      ...options,
      method: "PUT",
      body: body ? JSON.stringify(body) : undefined,
    });
  }

  public delete<T>(path: string, options?: RequestOptions): Promise<T> {
    return this.request<T>(path, { ...options, method: "DELETE" });
  }

  // Domain-specific endpoints
  public getHealth(): Promise<HealthResponse> {
    return this.get<HealthResponse>("/health");
  }

  public getEngagements(): Promise<EngagementSummary[]> {
    return this.get<EngagementSummary[]>("/api/v1/engagements");
  }

  public createEngagement(roePayload: Record<string, unknown>): Promise<EngagementSummary> {
    return this.post<EngagementSummary>("/api/v1/engagements", roePayload);
  }

  public submitApproval(payload: ApprovalDecisionPayload): Promise<{ success: boolean; gate_id: string }> {
    return this.post<{ success: boolean; gate_id: string }>(`/api/v1/approvals/${payload.gate_id}`, payload);
  }

  public triggerKillSwitch(engagementId?: string): Promise<{ success: boolean; message: string }> {
    return this.post<{ success: boolean; message: string }>("/api/v1/kill-switch", {
      engagement_id: engagementId,
      timestamp_utc: new Date().toISOString(),
    });
  }
}

export const apiClient = new ApiClient();
export default apiClient;
