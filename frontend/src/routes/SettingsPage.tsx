import React from "react";
import { Settings, Cpu, HardDrive, ShieldAlert, Sparkles } from "lucide-react";
import { Button, Card, CardHeader, CardTitle, CardContent, Badge, Select, Input } from "../components/ui";

export const SettingsPage: React.FC = () => {
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-100 flex items-center gap-2">
            <Settings className="w-5 h-5 text-primary" />
            System & Simulator Configuration
            <Badge variant="purple" size="sm">
              Local-First
            </Badge>
          </h1>
          <p className="text-xs text-gray-400 mt-1">
            Manage LLM provider backends, sandbox runtime limits, and telemetry settings.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* LLM Provider Configuration */}
        <Card variant="default">
          <CardHeader>
            <CardTitle>
              <Sparkles className="w-4 h-4 text-purple-400" />
              LLM Provider & Reasoning Engine (ADR-006)
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <Select label="Active Provider Backend" defaultValue="mock">
              <option value="mock">Mock Test Brain (Deterministic / Offline)</option>
              <option value="anthropic">Anthropic (Claude 3.5 Sonnet)</option>
              <option value="openai">OpenAI (GPT-4o)</option>
              <option value="ollama">Ollama / vLLM (Local Air-Gapped)</option>
            </Select>

            <Input
              label="CISO Reasoning Temperature"
              type="number"
              defaultValue={0.2}
              step={0.1}
              min={0}
              max={1}
            />
          </CardContent>
        </Card>

        {/* Sandbox & Isolation Configuration */}
        <Card variant="default">
          <CardHeader>
            <CardTitle>
              <Cpu className="w-4 h-4 text-blue-400" />
              Agent Execution Sandboxing (ADR-005)
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <Select label="Sandbox Isolation Mode" defaultValue="subprocess">
              <option value="subprocess">Subprocess + POSIX Limits + CWD Jail (MVP)</option>
              <option value="docker" disabled>
                Docker Container Isolation (Phase P25+)
              </option>
            </Select>

            <div className="grid grid-cols-2 gap-3">
              <Input label="RAM Quota (MB)" type="number" defaultValue={1024} />
              <Input label="Max CPU Timeout (s)" type="number" defaultValue={60} />
            </div>
          </CardContent>
        </Card>

        {/* Persistence & Tri-Store Storage */}
        <Card variant="default">
          <CardHeader>
            <CardTitle>
              <HardDrive className="w-4 h-4 text-emerald-400" />
              Storage & Audit Persistence (ADR-004)
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-xs text-gray-300">
            <div className="flex justify-between p-2 rounded bg-background">
              <span className="text-gray-400">Relational Store:</span>
              <span className="font-mono text-emerald-400">SQLite (WAL mode enabled)</span>
            </div>
            <div className="flex justify-between p-2 rounded bg-background">
              <span className="text-gray-400">Event Sourcing:</span>
              <span className="font-mono text-emerald-400">Append-Only Monotonic Log</span>
            </div>
            <div className="flex justify-between p-2 rounded bg-background">
              <span className="text-gray-400">Artifact Directory:</span>
              <span className="font-mono text-gray-400">./data/engagements/</span>
            </div>
          </CardContent>
        </Card>

        {/* Emergency Safety Protocol */}
        <Card variant="default" className="border-red-900/40">
          <CardHeader>
            <CardTitle className="text-red-300">
              <ShieldAlert className="w-4 h-4 text-danger" />
              Emergency Protocol & Kill Switch
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-xs text-gray-400 leading-relaxed">
              Emergency stop signals broadcast POSIX `SIGKILL` to all agent process groups in &lt; 200ms.
            </p>

            <Button variant="danger" size="sm" fullWidth>
              Test Emergency Stop Signal (Dry Run)
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>
  );
};

export default SettingsPage;
