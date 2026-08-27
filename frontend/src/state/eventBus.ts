/**
 * Central EventBus for Dispatching WebSocket & Replay Events to Zustand Stores
 */

import { useEventStore } from "./eventStore";
import { useConnectionStore } from "./connectionStore";
import {
  AgentEntity,
  ApprovalGateEntity,
  FindingEntity,
  RedCellEventEnvelope,
  TaskEntity,
  TerminalLogEntry,
} from "../types/events";

export type EventHandler = (event: RedCellEventEnvelope) => void;

class EventBus {
  private handlers: Map<string, Set<EventHandler>> = new Map();

  constructor() {
    this._registerCoreStoreReducers();
  }

  /**
   * Subscribe an external custom handler to a specific event type.
   */
  public on(eventType: string, handler: EventHandler): () => void {
    if (!this.handlers.has(eventType)) {
      this.handlers.set(eventType, new Set());
    }
    this.handlers.get(eventType)!.add(handler);

    return () => {
      const handlers = this.handlers.get(eventType);
      if (handlers) {
        handlers.delete(handler);
        if (handlers.size === 0) {
          this.handlers.delete(eventType);
        }
      }
    };
  }

  /**
   * Dispatch an incoming event through store reducers and custom subscribers.
   */
  public dispatch(event: RedCellEventEnvelope): void {
    const rawSeq = event.seq_num ?? (event as unknown as { seq: number }).seq ?? 0;
    const normalizedEvent: RedCellEventEnvelope = {
      ...event,
      seq_num: rawSeq,
    };

    // 1. Record raw event in eventStore history
    useEventStore.getState().applyEvent(normalizedEvent);

    // 2. Invoke registered handlers for this specific event type
    const specificHandlers = this.handlers.get(normalizedEvent.event_type);
    if (specificHandlers) {
      specificHandlers.forEach((handler) => {
        try {
          handler(normalizedEvent);
        } catch (err) {
          console.error(`Error in event handler for '${normalizedEvent.event_type}':`, err);
        }
      });
    }

    // 3. Invoke wildcard ('*') handlers
    const wildcardHandlers = this.handlers.get("*");
    if (wildcardHandlers) {
      wildcardHandlers.forEach((handler) => {
        try {
          handler(normalizedEvent);
        } catch (err) {
          console.error("Error in wildcard event handler:", err);
        }
      });
    }
  }

  /**
   * Internal reducers updating the normalized entity tables in Zustand.
   */
  private _registerCoreStoreReducers(): void {
    // 1. Connection Handshake
    this.on("connection_established", () => {
      useConnectionStore.getState().setStatus("CONNECTED");
      useEventStore.getState().setConnected(true);
    });

    // 2. Agent Lifecycle & State Changes
    this.on("agent_state_changed", (event) => {
      if (!event.agent_id) return;
      const store = useEventStore.getState();
      const existing = store.agents[event.agent_id];
      const payload = event.payload as {
        current_state?: string;
        previous_state?: string;
        role?: string;
        department?: string;
        name?: string;
      };

      const nextState = (payload.current_state || existing?.state || "IDLE") as AgentEntity["state"];

      const updatedAgent: AgentEntity = {
        agent_id: event.agent_id,
        name: payload.name || existing?.name || event.agent_id,
        role: (payload.role || existing?.role || "role_web_discovery") as AgentEntity["role"],
        department: payload.department || existing?.department || event.department_id || "dept_recon",
        state: nextState,
        current_task_id: event.task_id || existing?.current_task_id,
        x: existing?.x || 100,
        y: existing?.y || 100,
        last_active_at: event.timestamp_utc,
      };

      store.upsertAgent(updatedAgent);
    });

    // 3. Task Lifecycle (Created, Started, Completed, Failed)
    this.on("task_created", (event) => {
      const payload = event.payload as Partial<TaskEntity>;
      if (!event.task_id) return;

      const task: TaskEntity = {
        task_id: event.task_id,
        title: payload.title || `Task ${event.task_id}`,
        department_id: event.department_id || "dept_recon",
        assigned_role: (payload.assigned_role || "role_web_discovery") as TaskEntity["assigned_role"],
        assigned_agent_id: event.agent_id,
        state: "PENDING",
        depends_on: payload.depends_on || [],
        requires_approval_gate: payload.requires_approval_gate,
        created_at: event.timestamp_utc,
      };
      useEventStore.getState().upsertTask(task);
    });

    this.on("task_started", (event) => {
      if (!event.task_id) return;
      const existing = useEventStore.getState().tasks[event.task_id];
      if (existing) {
        useEventStore.getState().upsertTask({
          ...existing,
          state: "RUNNING",
          started_at: event.timestamp_utc,
          assigned_agent_id: event.agent_id || existing.assigned_agent_id,
        });
      }
    });

    this.on("task_completed", (event) => {
      if (!event.task_id) return;
      const existing = useEventStore.getState().tasks[event.task_id];
      if (existing) {
        useEventStore.getState().upsertTask({
          ...existing,
          state: "COMPLETED",
          completed_at: event.timestamp_utc,
        });
      }
    });

    this.on("task_failed", (event) => {
      if (!event.task_id) return;
      const existing = useEventStore.getState().tasks[event.task_id];
      if (existing) {
        useEventStore.getState().upsertTask({
          ...existing,
          state: "FAILED",
          completed_at: event.timestamp_utc,
        });
      }
    });

    // 4. Human-in-the-Loop Approval Gates
    this.on("approval_requested", (event) => {
      const payload = event.payload as {
        gate_id?: string;
        category?: string;
        target_uri?: string;
        risk_description?: string;
      };
      const gateId = payload.gate_id || `gate-${event.seq_num}`;

      const approval: ApprovalGateEntity = {
        gate_id: gateId,
        engagement_id: event.engagement_id || "eng-mvp-001",
        task_id: event.task_id || "TASK-00",
        agent_id: event.agent_id || "agent-vuln-01",
        category: payload.category || "ACTIVE_EXPLOITATION_PROBE",
        target_uri: payload.target_uri || "http://127.0.0.1:8088",
        risk_description: payload.risk_description || "Pending operator authorization",
        status: "PENDING",
        requested_at: event.timestamp_utc,
      };

      useEventStore.getState().upsertApproval(approval);
    });

    this.on("approval_decided", (event) => {
      const payload = event.payload as {
        gate_id?: string;
        decision?: "GRANTED" | "REJECTED";
        decided_by?: string;
      };
      if (!payload.gate_id) return;

      const existing = useEventStore.getState().approvals[payload.gate_id];
      if (existing) {
        useEventStore.getState().upsertApproval({
          ...existing,
          status: payload.decision || "GRANTED",
          decided_at: event.timestamp_utc,
          decided_by: payload.decided_by || "Operator",
        });
      }
    });

    // 5. Finding Discovered & Recorded
    this.on("finding_recorded", (event) => {
      const payload = event.payload as Partial<FindingEntity>;
      const findingId = payload.finding_id || `FINDING-${event.seq_num}`;

      const finding: FindingEntity = {
        finding_id: findingId,
        engagement_id: event.engagement_id || "eng-mvp-001",
        title: payload.title || "Discovered Security Vulnerability",
        severity: payload.severity || "HIGH",
        cvss_score: payload.cvss_score ?? 7.5,
        cvss_vector: payload.cvss_vector,
        cwe_id: payload.cwe_id || "CWE-200",
        target_endpoint: payload.target_endpoint || "http://127.0.0.1:8088",
        description: payload.description || "Identified security flaw in target scope.",
        discovered_by_agent: event.agent_id || "agent-vuln-01",
        evidence_summary: payload.evidence_summary,
        remediation: payload.remediation,
        timestamp_utc: event.timestamp_utc,
      };

      useEventStore.getState().upsertFinding(finding);
    });

    // 6. Terminal Logs & Command Streaming
    this.on("command_executed", (event) => {
      const payload = event.payload as { command?: string; target?: string };
      const logEntry: TerminalLogEntry = {
        id: `log-${event.seq_num}`,
        timestamp_utc: event.timestamp_utc,
        source: "agent",
        level: "info",
        text: `Executing: ${payload.command || "command"} against ${payload.target || "target"}`,
        agent_id: event.agent_id,
        task_id: event.task_id,
        correlation_id: event.correlation_id,
      };
      useEventStore.getState().appendLog(logEntry);
    });

    this.on("stdout_chunk", (event) => {
      const payload = event.payload as { text?: string; chunk?: string };
      const logEntry: TerminalLogEntry = {
        id: `log-${event.seq_num}`,
        timestamp_utc: event.timestamp_utc,
        source: "tool",
        level: "info",
        text: payload.text || payload.chunk || "",
        agent_id: event.agent_id,
        task_id: event.task_id,
        correlation_id: event.correlation_id,
      };
      useEventStore.getState().appendLog(logEntry);
    });

    // 7. Global Emergency Kill Switch
    this.on("kill_switch_tripped", () => {
      const store = useEventStore.getState();
      const updatedAgents = { ...store.agents };

      Object.keys(updatedAgents).forEach((agentId) => {
        updatedAgents[agentId] = {
          ...updatedAgents[agentId],
          state: "EMERGENCY_HALTED",
        };
      });

      useEventStore.setState({ agents: updatedAgents });
      useEventStore.getState().appendLog({
        id: `log-kill-${Date.now()}`,
        timestamp_utc: new Date().toISOString(),
        source: "system",
        level: "error",
        text: "🚨 EMERGENCY KILL SWITCH TRIPPED: All agent workspaces and subprocesses halted.",
      });
    });
  }
}

export const eventBus = new EventBus();
export default eventBus;
