import React from "react";
import { useEventStore } from "../state/eventStore";

export const OfficeCanvas: React.FC = () => {
  const agents = useEventStore((state) => state.agents);
  const agentList = Object.values(agents);

  return (
    <div className="relative w-full h-[540px] bg-surface rounded-xl border border-surfaceBorder overflow-hidden flex flex-col items-center justify-center p-6 text-center">
      <div className="absolute inset-0 bg-[radial-gradient(#30363d_1px,transparent_1px)] [background-size:16px_16px] opacity-40"></div>
      <div className="relative z-10 max-w-md">
        <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-primary/10 border border-primary/30 flex items-center justify-center text-primary text-2xl font-bold">
          🏢
        </div>
        <h3 className="text-xl font-semibold text-gray-100">
          2D Office Simulation Viewport
        </h3>
        <p className="text-sm text-gray-400 mt-2">
          PixiJS WebGL canvas will project virtual cybersecurity departments,
          desks, and AI employee movements in real time.
        </p>
        <div className="mt-4 flex items-center justify-center gap-2">
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-950/80 text-emerald-400 border border-emerald-800">
            Active Agents: {agentList.length}
          </span>
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-950/80 text-blue-400 border border-blue-800">
            Engine: PixiJS WebGL
          </span>
        </div>
      </div>
    </div>
  );
};
