import React, { useState } from "react";
import { Target, Plus, ShieldCheck, FileJson } from "lucide-react";
import { Button, Card, CardHeader, CardTitle, CardContent, CardFooter, Badge, Alert, Modal, Input } from "../components/ui";

export const EngagementsPage: React.FC = () => {
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-100 flex items-center gap-2">
            <Target className="w-5 h-5 text-accent" />
            Engagements & Rules of Engagement (ROE)
            <Badge variant="success" size="sm">
              ROE Enforced
            </Badge>
          </h1>
          <p className="text-xs text-gray-400 mt-1">
            Manage authorized penetration testing scopes, time windows, and target allowlists.
          </p>
        </div>

        <Button
          variant="accent"
          size="sm"
          icon={<Plus className="w-4 h-4" />}
          onClick={() => setIsCreateModalOpen(true)}
        >
          Create New Scope
        </Button>
      </div>

      <Alert variant="info" title="Deterministic Boundary Safeguard (M002)">
        All agent command execution is intercepted at the kernel/subprocess boundary against this verified allowlist. Any out-of-scope targets are instantly blocked.
      </Alert>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <Card variant="default" className="md:col-span-2">
          <CardHeader>
            <CardTitle>
              <FileJson className="w-4 h-4 text-primary" />
              Active Engagement Manifest (MVP Scope)
            </CardTitle>
            <Badge variant="purple" size="sm">
              eng-mvp-001
            </Badge>
          </CardHeader>
          <CardContent>
            <div className="p-4 bg-background/90 rounded-lg border border-surfaceBorder font-mono text-xs text-gray-300 space-y-1 overflow-x-auto">
              <div><span className="text-purple-400">engagement_id:</span> "eng-mvp-001"</div>
              <div><span className="text-purple-400">allowed_cidrs:</span> ["127.0.0.1/32"]</div>
              <div><span className="text-purple-400">allowed_ports:</span> ["8088"]</div>
              <div><span className="text-purple-400">max_intensity:</span> "vulnerability_verification"</div>
              <div><span className="text-purple-400">approval_gates:</span> ["ACTIVE_EXPLOITATION_PROBE"]</div>
            </div>
          </CardContent>
        </Card>

        <Card variant="default" className="flex flex-col justify-between">
          <div>
            <CardHeader>
              <CardTitle>
                <ShieldCheck className="w-4 h-4 text-emerald-400" />
                Scope Validation Status
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-gray-400 mb-3">
                Deterministic kernel-level boundary checks enforce zero out-of-scope egress.
              </p>
              <div className="p-3 bg-emerald-950/40 border border-emerald-800/60 rounded-lg text-xs text-emerald-300 space-y-1">
                <div>✓ All target CIDRs allowlisted</div>
                <div>✓ Emergency freeze: OFF</div>
                <div>✓ Signature verification: VALID</div>
              </div>
            </CardContent>
          </div>

          <CardFooter>
            <Button variant="outline" size="sm" fullWidth>
              Upload Custom ROE Manifest (.json/.yaml)
            </Button>
          </CardFooter>
        </Card>
      </div>

      {/* Scope Creation Modal */}
      <Modal
        isOpen={isCreateModalOpen}
        onClose={() => setIsCreateModalOpen(false)}
        title="Create New Authorized Engagement Scope"
        description="Provide client organization authorization details and target allowlists."
        footer={
          <>
            <Button variant="ghost" size="sm" onClick={() => setIsCreateModalOpen(false)}>
              Cancel
            </Button>
            <Button variant="primary" size="sm" onClick={() => setIsCreateModalOpen(false)}>
              Save & Sign Scope
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Input label="Engagement ID" placeholder="eng-2026-audit-01" defaultValue="eng-custom-001" />
          <Input label="Target CIDR Allowlist" placeholder="192.168.1.0/24, 10.0.0.0/16" defaultValue="127.0.0.1/32" />
          <Input label="Target Ports" placeholder="80, 443, 8000-8090" defaultValue="8088" />
        </div>
      </Modal>
    </div>
  );
};

export default EngagementsPage;
