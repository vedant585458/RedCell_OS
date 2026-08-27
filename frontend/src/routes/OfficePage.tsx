import React from "react";
import { OfficeCanvas } from "../world/OfficeCanvas";
import { Users, Layers } from "lucide-react";

export const OfficePage: React.FC = () => {
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-100 flex items-center gap-2">
            <Users className="w-5 h-5 text-primary" />
            2D Virtual Office Simulation
          </h1>
          <p className="text-xs text-gray-400 mt-1">
            Real-time visual projection of AI cybersecurity departments and agent workflows.
          </p>
        </div>

        <div className="flex items-center gap-2 text-xs">
          <span className="px-2.5 py-1 bg-surface border border-surfaceBorder rounded-md text-gray-300 flex items-center gap-1.5">
            <Layers className="w-3.5 h-3.5 text-primary" />
            6 Departments
          </span>
          <span className="px-2.5 py-1 bg-surface border border-surfaceBorder rounded-md text-emerald-400">
            WebGL 60 FPS
          </span>
        </div>
      </div>

      <div className="w-full">
        <OfficeCanvas />
      </div>
    </div>
  );
};

export default OfficePage;
