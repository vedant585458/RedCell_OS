import React from "react";
import { Shield, Radio } from "lucide-react";
import { useEventStore } from "../state/eventStore";
import { BackendStatus } from "./BackendStatus";

export const AppHeader: React.FC = () => {
  const isConnected = useEventStore((state) => state.isConnected);
  const lastSeenSeq = useEventStore((state) => state.lastSeenSeq);

  return (
    <header className="flex items-center justify-between px-6 py-4 bg-surface border-b border-surfaceBorder">
      <div className="flex items-center gap-3">
        <div className="p-2 bg-red-950/60 border border-red-800/80 rounded-lg text-red-400">
          <Shield className="w-6 h-6" />
        </div>
        <div>
          <h1 className="text-lg font-bold text-gray-100 tracking-wide flex items-center gap-2">
            RedCell_OS
            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-surfaceBorder text-gray-300 font-normal">
              v0.1.0-alpha
            </span>
          </h1>
          <p className="text-xs text-gray-400">
            AI-Agentic Penetration Testing Organization Simulator
          </p>
        </div>
      </div>

      <div className="flex items-center gap-3">
        {/* Real-time Backend Health Status Badge */}
        <BackendStatus />

        {/* Real-time WebSocket Event Stream Status */}
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-background border border-surfaceBorder text-xs">
          <Radio
            className={`w-3.5 h-3.5 ${
              isConnected ? "text-emerald-400 animate-pulse" : "text-gray-500"
            }`}
          />
          <span className="text-gray-300">
            {isConnected ? "Event Stream Live" : "WS Standby"}
          </span>
          <span className="text-gray-500">|</span>
          <span className="font-mono text-gray-400">Seq: {lastSeenSeq}</span>
        </div>

        {/* Global Emergency Kill Switch */}
        <button
          className="px-3.5 py-1.5 bg-danger/90 hover:bg-danger text-white rounded-lg text-xs font-semibold tracking-wide transition shadow-sm"
          title="Global Emergency Kill Switch (< 200ms)"
        >
          EMERGENCY STOP
        </button>
      </div>
    </header>
  );
};
