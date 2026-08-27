/**
 * RedCell_OS Canonical Event Definitions and Entity Models
 */

export type AgentRole =
  | "role_ciso"
  | "role_engagement_manager"
  | "role_passive_osint"
  | "role_active_network_recon"
  | "role_web_discovery"
  | "role_infra_vuln_assessor"
  | "role_web_vuln_assessor"
  | "role_cloud_container_assessor"
  | "role_exploit_verifier"
  | "role_privesc_credential_analyst"
  | "role_adversary_emulator"
  | "role_detection_analyst"
  | "role_remediation_advisor"
  | "role_technical_writer"
  | "role_executive_briefer"
  | "role_safety_sentinel";

export type AgentState =
  | "IDLE"
  | "PLANNING"
  | "AWAITING_APPROVAL"
  | "EXECUTING"
  | "REPORTING"
  | "COMPLETED"
  | "FAILED"
  | "EMERGENCY_HALTED";

export type TaskState =
  | "PENDING"
  | "RUNNING"
  | "AWAITING_APPROVAL"
  | "COMPLETED"
  | "FAILED"
  | "BLOCKED";

export type FindingSeverity =
  | "CRITICAL"
  | "HIGH"
  | "MEDIUM"
  | "LOW"
  | "INFORMATIONAL";

export interface AgentEntity {
  agent_id: string;
  role: AgentRole;
  name: string;
  department: string;
  state: AgentState;
  current_task_id?: string;
  x: number;
  y: number;
  last_active_at?: string;
}

export interface TaskEntity {
  task_id: string;
  title: string;
  department_id: string;
  assigned_role: AgentRole;
  assigned_agent_id?: string;
  state: TaskState;
  depends_on: string[];
  requires_approval_gate?: string;
  created_at: string;
  started_at?: string;
  completed_at?: string;
}

export interface FindingEntity {
  finding_id: string;
  engagement_id: string;
  title: string;
  severity: FindingSeverity;
  cvss_score: number;
  cvss_vector?: string;
  cwe_id: string;
  target_endpoint: string;
  description: string;
  discovered_by_agent: string;
  evidence_summary?: string;
  remediation?: string;
  timestamp_utc: string;
}

export interface ApprovalGateEntity {
  gate_id: string;
  engagement_id: string;
  task_id: string;
  agent_id: string;
  category: string;
  target_uri: string;
  risk_description: string;
  status: "PENDING" | "GRANTED" | "REJECTED" | "EXPIRED";
  requested_at: string;
  decided_at?: string;
  decided_by?: string;
}

export interface TerminalLogEntry {
  id: string;
  timestamp_utc: string;
  source: "agent" | "tool" | "system" | "orchestrator";
  level: "info" | "warn" | "error" | "debug";
  text: string;
  agent_id?: string;
  task_id?: string;
  correlation_id?: string;
}

export interface BaseEventEnvelope {
  seq_num: number;
  event_type: string;
  correlation_id: string;
  engagement_id?: string;
  agent_id?: string;
  department_id?: string;
  task_id?: string;
  timestamp_utc: string;
  payload: Record<string, unknown>;
}

// Aliases for compatibility
export type RedCellEvent = BaseEventEnvelope;
export type RedCellEventEnvelope = BaseEventEnvelope;
