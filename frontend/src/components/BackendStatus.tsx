import React from "react";
import { CheckCircle2, AlertTriangle, XCircle, RefreshCw, Activity } from "lucide-react";
import { useConnectionStore, ConnectionStatus } from "../state/connectionStore";

const STATUS_CONFIG: Record<
  ConnectionStatus,
  {
    label: string;
    badgeClass: string;
    dotClass: string;
    icon: React.ReactNode;
    description: string;
  }
> = {
  CONNECTED: {
    label: "Backend Online",
    badgeClass: "bg-emerald-950/60 text-emerald-400 border-emerald-800/80 hover:bg-emerald-950/80",
    dotClass: "bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.6)]",
    icon: <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />,
    description: "FastAPI control plane is healthy and responsive.",
  },
  CONNECTING: {
    label: "Connecting...",
    badgeClass: "bg-blue-950/60 text-blue-400 border-blue-800/80 animate-pulse",
    dotClass: "bg-blue-400 animate-ping",
    icon: <RefreshCw className="w-3.5 h-3.5 text-blue-400 animate-spin" />,
    description: "Establishing initial handshake with backend process.",
  },
  DEGRADED: {
    label: "High Latency",
    badgeClass: "bg-amber-950/60 text-amber-400 border-amber-800/80",
    dotClass: "bg-amber-400",
    icon: <Activity className="w-3.5 h-3.5 text-amber-400" />,
    description: "Backend is responding slowly (> 1200ms).",
  },
  DISCONNECTED: {
    label: "Disconnected",
    badgeClass: "bg-orange-950/60 text-orange-400 border-orange-800/80",
    dotClass: "bg-orange-400",
    icon: <AlertTriangle className="w-3.5 h-3.5 text-orange-400" />,
    description: "Health probe failed. Supervisor may be restarting backend.",
  },
  FAILED: {
    label: "Backend Offline (Circuit Tripped)",
    badgeClass: "bg-red-950/80 text-red-400 border-red-700 font-semibold",
    dotClass: "bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.8)]",
    icon: <XCircle className="w-3.5 h-3.5 text-red-400" />,
    description: "Multiple consecutive health failures. Check terminal logs.",
  },
};

export const BackendStatus: React.FC = () => {
  const status = useConnectionStore((state) => state.status);
  const latencyMs = useConnectionStore((state) => state.latencyMs);
  const backendVersion = useConnectionStore((state) => state.backendVersion);
  const consecutiveFailures = useConnectionStore((state) => state.consecutiveFailures);
  const checkHealth = useConnectionStore((state) => state.checkHealth);

  const config = STATUS_CONFIG[status] || STATUS_CONFIG.CONNECTING;

  return (
    <div
      className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs transition-all shadow-sm ${config.badgeClass}`}
      title={config.description}
    >
      <span className="relative flex h-2 w-2">
        <span className={`relative inline-flex rounded-full h-2 w-2 ${config.dotClass}`}></span>
      </span>

      <span className="font-medium tracking-wide">{config.label}</span>

      {latencyMs !== null && status === "CONNECTED" && (
        <>
          <span className="text-gray-500">|</span>
          <span className="font-mono text-[11px] text-gray-300">{latencyMs}ms</span>
        </>
      )}

      {backendVersion && status === "CONNECTED" && (
        <span className="text-[10px] text-gray-400 bg-background/50 px-1.5 py-0.5 rounded">
          v{backendVersion}
        </span>
      )}

      {(status === "DISCONNECTED" || status === "FAILED") && (
        <button
          onClick={() => checkHealth()}
          className="ml-1 px-1.5 py-0.5 bg-background/80 hover:bg-background text-gray-200 rounded text-[10px] border border-surfaceBorder flex items-center gap-1 transition"
          title="Retry Health Check"
        >
          <RefreshCw className="w-2.5 h-2.5" />
          Retry ({consecutiveFailures})
        </button>
      )}
    </div>
  );
};
