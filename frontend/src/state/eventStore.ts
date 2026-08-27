import { create } from "zustand";
import {
  AgentEntity,
  ApprovalGateEntity,
  FindingEntity,
  RedCellEvent,
  TaskEntity,
  TerminalLogEntry,
} from "../types/events";

export interface EventStoreState {
  isConnected: boolean;
  engagementId: string | null;
  lastSeenSeq: number;

  // Domain Entity Tables
  agents: Record<string, AgentEntity>;
  tasks: Record<string, TaskEntity>;
  findings: Record<string, FindingEntity>;
  approvals: Record<string, ApprovalGateEntity>;
  logs: TerminalLogEntry[];
  events: RedCellEvent[];

  // Mutations
  setConnected: (connected: boolean) => void;
  setEngagementId: (id: string) => void;
  applyEvent: (event: RedCellEvent) => void;
  upsertAgent: (agent: AgentEntity) => void;
  upsertTask: (task: TaskEntity) => void;
  upsertFinding: (finding: FindingEntity) => void;
  upsertApproval: (approval: ApprovalGateEntity) => void;
  appendLog: (log: TerminalLogEntry) => void;
  reset: () => void;
}

export const useEventStore = create<EventStoreState>((set) => ({
  isConnected: false,
  engagementId: null,
  lastSeenSeq: 0,

  agents: {},
  tasks: {},
  findings: {},
  approvals: {},
  logs: [],
  events: [],

  setConnected: (connected) => set({ isConnected: connected }),

  setEngagementId: (id) => set({ engagementId: id }),

  upsertAgent: (agent) =>
    set((state) => ({
      agents: { ...state.agents, [agent.agent_id]: agent },
    })),

  upsertTask: (task) =>
    set((state) => ({
      tasks: { ...state.tasks, [task.task_id]: task },
    })),

  upsertFinding: (finding) =>
    set((state) => ({
      findings: { ...state.findings, [finding.finding_id]: finding },
    })),

  upsertApproval: (approval) =>
    set((state) => ({
      approvals: { ...state.approvals, [approval.gate_id]: approval },
    })),

  appendLog: (log) =>
    set((state) => ({
      logs: [...state.logs.slice(-499), log], // Cap at last 500 lines
    })),

  applyEvent: (event) =>
    set((state) => {
      const seq = event.seq_num ?? (event as unknown as { seq: number }).seq ?? 0;
      const updatedEvents = [...state.events, event];
      const updatedAgents = { ...state.agents };

      // Basic agent state update fallback
      if (event.agent_id && updatedAgents[event.agent_id]) {
        if (event.event_type === "agent_state_changed") {
          const payload = event.payload as { current_state?: string };
          if (payload.current_state) {
            updatedAgents[event.agent_id] = {
              ...updatedAgents[event.agent_id],
              state: payload.current_state as AgentEntity["state"],
            };
          }
        }
      }

      return {
        lastSeenSeq: Math.max(state.lastSeenSeq, seq),
        events: updatedEvents,
        agents: updatedAgents,
      };
    }),

  reset: () =>
    set({
      isConnected: false,
      engagementId: null,
      lastSeenSeq: 0,
      agents: {},
      tasks: {},
      findings: {},
      approvals: {},
      logs: [],
      events: [],
    }),
}));
