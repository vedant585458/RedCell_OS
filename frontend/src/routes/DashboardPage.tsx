import React, { useState } from "react";
import { Shield, Target, Users, AlertCircle, Play, FileCode, Sparkles } from "lucide-react";
import { useConnectionStore } from "../state/connectionStore";
import { Link } from "react-router-dom";
import { Button, Card, CardHeader, CardTitle, CardContent, CardFooter, Badge, Alert, Modal } from "../components/ui";

export const DashboardPage: React.FC = () => {
  const backendStatus = useConnectionStore((state) => state.status);
  const backendVersion = useConnectionStore((state) => state.backendVersion);
  const [isQuickLaunchOpen, setIsQuickLaunchOpen] = useState(false);

  return (
    <div className="space-y-6">
      {/* Top Header Row */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-100 flex items-center gap-2">
            Operations Command Center
            <Badge variant="purple" size="sm" icon={<Sparkles className="w-3 h-3" />}>
              Multi-Agent AI
            </Badge>
          </h1>
          <p className="text-xs text-gray-400 mt-1">
            Real-time telemetry and multi-agent coordination overview.
          </p>
        </div>
        <div className="flex gap-2">
          <Link to="/office">
            <Button variant="outline" size="sm" icon={<Users className="w-4 h-4" />}>
              View Office Sim
            </Button>
          </Link>
          <Button
            variant="accent"
            size="sm"
            icon={<Play className="w-4 h-4" />}
            onClick={() => setIsQuickLaunchOpen(true)}
          >
            Quick Launch
          </Button>
        </div>
      </div>

      {/* Alert Banner Example */}
      {backendStatus !== "CONNECTED" && (
        <Alert
          variant="warning"
          title="Backend Supervisor Notice"
        >
          FastAPI control plane is currently {backendStatus.toLowerCase()}. Simulation events will queue until connection is established.
        </Alert>
      )}

      {/* Metrics Row using Card & Badge Primitives */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card variant="default" glow className="p-4 flex items-center gap-3.5">
          <div className="p-2.5 rounded-lg bg-blue-950/60 border border-blue-800/80 text-blue-400">
            <Shield className="w-5 h-5" />
          </div>
          <div>
            <span className="text-[11px] text-gray-400 uppercase tracking-wider block font-medium">
              Control Plane
            </span>
            <div className="flex items-center gap-1.5 mt-0.5">
              <Badge variant={backendStatus === "CONNECTED" ? "success" : "warning"} dot pulse>
                {backendStatus} {backendVersion ? `v${backendVersion}` : ""}
              </Badge>
            </div>
          </div>
        </Card>

        <Card variant="default" glow className="p-4 flex items-center gap-3.5">
          <div className="p-2.5 rounded-lg bg-purple-950/60 border border-purple-800/80 text-purple-400">
            <Target className="w-5 h-5" />
          </div>
          <div>
            <span className="text-[11px] text-gray-400 uppercase tracking-wider block font-medium">
              Active Missions
            </span>
            <span className="text-sm font-bold text-gray-100">0 Running</span>
          </div>
        </Card>

        <Card variant="default" glow className="p-4 flex items-center gap-3.5">
          <div className="p-2.5 rounded-lg bg-emerald-950/60 border border-emerald-800/80 text-emerald-400">
            <Users className="w-5 h-5" />
          </div>
          <div>
            <span className="text-[11px] text-gray-400 uppercase tracking-wider block font-medium">
              AI Employees
            </span>
            <span className="text-sm font-bold text-gray-100">16 Roles Ready</span>
          </div>
        </Card>

        <Card variant="default" glow className="p-4 flex items-center gap-3.5">
          <div className="p-2.5 rounded-lg bg-amber-950/60 border border-amber-800/80 text-amber-400">
            <AlertCircle className="w-5 h-5" />
          </div>
          <div>
            <span className="text-[11px] text-gray-400 uppercase tracking-wider block font-medium">
              Approval Gates
            </span>
            <Badge variant="default" size="sm">
              0 Pending
            </Badge>
          </div>
        </Card>
      </div>

      {/* Main Dashboard Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card variant="default" className="lg:col-span-2">
          <CardHeader>
            <CardTitle>
              <span className="w-2 h-2 rounded-full bg-primary"></span>
              Recent Engagements & Telemetry
            </CardTitle>
            <Link to="/engagements" className="text-xs text-primary hover:underline font-medium">
              View All
            </Link>
          </CardHeader>
          <CardContent className="py-12 text-center text-gray-500">
            <FileCode className="w-10 h-10 mx-auto mb-2 opacity-40 text-gray-400" />
            <p className="text-xs text-gray-400 font-medium">No security engagements executed yet.</p>
            <p className="text-[11px] text-gray-500 mt-1">
              Submit a Rules of Engagement (ROE) manifest to launch the CISO orchestrator.
            </p>
          </CardContent>
        </Card>

        <Card variant="default" className="flex flex-col justify-between">
          <div>
            <CardHeader>
              <CardTitle>
                <span className="w-2 h-2 rounded-full bg-accent"></span>
                Quick Launch Wizard
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-gray-400 mb-3">
                Bootstrap an engagement against a local sandboxed target.
              </p>
              <div className="p-3 bg-background/80 rounded-lg border border-surfaceBorder text-xs text-gray-300 font-mono space-y-1">
                <div>Target: http://127.0.0.1:8088</div>
                <div>Scope: eng-mvp-001</div>
                <div>Mode: Safe Verification</div>
              </div>
            </CardContent>
          </div>

          <CardFooter>
            <Link to="/engagements" className="w-full">
              <Button variant="outline" size="sm" fullWidth>
                Configure Scope in Engagements &rarr;
              </Button>
            </Link>
          </CardFooter>
        </Card>
      </div>

      {/* Quick Launch Modal Primitive */}
      <Modal
        isOpen={isQuickLaunchOpen}
        onClose={() => setIsQuickLaunchOpen(false)}
        title="Quick Launch MVP Mission"
        description="Initialize engagement 'eng-mvp-001' against local sandboxed target (Port 8088)."
        footer={
          <>
            <Button variant="ghost" size="sm" onClick={() => setIsQuickLaunchOpen(false)}>
              Cancel
            </Button>
            <Button variant="accent" size="sm" onClick={() => setIsQuickLaunchOpen(false)}>
              Start Engagement
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <p className="text-xs text-gray-300">
            The CISO Agent will decompose the mission into 3 tasks across departments:
          </p>
          <ol className="list-decimal list-inside space-y-1 text-xs text-gray-400 font-mono">
            <li>Reconnaissance (Web discovery on port 8088)</li>
            <li>Vulnerability Assessment (Debug config validation)</li>
            <li>Reporting (CVSS report generation)</li>
          </ol>
        </div>
      </Modal>
    </div>
  );
};

export default DashboardPage;
