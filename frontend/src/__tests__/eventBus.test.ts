import { describe, it, expect, vi, beforeEach } from "vitest";
import { eventBus } from "../state/eventBus";
import { useEventStore } from "../state/eventStore";
import { useConnectionStore } from "../state/connectionStore";

describe("EventBus Dispatcher and Store Integration", () => {
  beforeEach(() => {
    useEventStore.getState().reset();
    useConnectionStore.getState().reset();
  });

  it("updates agent state on 'agent_state_changed' event", () => {
    eventBus.dispatch({
      seq_num: 1,
      event_type: "agent_state_changed",
      correlation_id: "corr-01",
      agent_id: "agent-recon-01",
      department_id: "dept_recon",
      timestamp_utc: new Date().toISOString(),
      payload: {
        current_state: "EXECUTING",
        role: "role_web_discovery",
        name: "Recon Agent Alpha",
      },
    });

    const agent = useEventStore.getState().agents["agent-recon-01"];
    expect(agent).toBeDefined();
    expect(agent.state).toBe("EXECUTING");
    expect(agent.name).toBe("Recon Agent Alpha");
    expect(agent.department).toBe("dept_recon");
  });

  it("creates and updates tasks through task lifecycle events", () => {
    // 1. Task Created
    eventBus.dispatch({
      seq_num: 2,
      event_type: "task_created",
      correlation_id: "corr-02",
      task_id: "TASK-01",
      agent_id: "agent-recon-01",
      department_id: "dept_recon",
      timestamp_utc: new Date().toISOString(),
      payload: {
        title: "Web Discovery on Port 8088",
        assigned_role: "role_web_discovery",
        depends_on: [],
      },
    });

    let task = useEventStore.getState().tasks["TASK-01"];
    expect(task).toBeDefined();
    expect(task.state).toBe("PENDING");
    expect(task.title).toBe("Web Discovery on Port 8088");

    // 2. Task Started
    eventBus.dispatch({
      seq_num: 3,
      event_type: "task_started",
      correlation_id: "corr-02",
      task_id: "TASK-01",
      agent_id: "agent-recon-01",
      timestamp_utc: new Date().toISOString(),
      payload: {},
    });

    task = useEventStore.getState().tasks["TASK-01"];
    expect(task.state).toBe("RUNNING");

    // 3. Task Completed
    eventBus.dispatch({
      seq_num: 4,
      event_type: "task_completed",
      correlation_id: "corr-02",
      task_id: "TASK-01",
      timestamp_utc: new Date().toISOString(),
      payload: {},
    });

    task = useEventStore.getState().tasks["TASK-01"];
    expect(task.state).toBe("COMPLETED");
  });

  it("records human approval request on 'approval_requested'", () => {
    eventBus.dispatch({
      seq_num: 5,
      event_type: "approval_requested",
      correlation_id: "corr-03",
      task_id: "TASK-02",
      agent_id: "agent-vuln-01",
      timestamp_utc: new Date().toISOString(),
      payload: {
        gate_id: "gate-req-001",
        category: "ACTIVE_EXPLOITATION_PROBE",
        target_uri: "http://127.0.0.1:8088/api/v1/debug/config",
        risk_description: "Probe unauthenticated configuration endpoint",
      },
    });

    const approval = useEventStore.getState().approvals["gate-req-001"];
    expect(approval).toBeDefined();
    expect(approval.status).toBe("PENDING");
    expect(approval.category).toBe("ACTIVE_EXPLOITATION_PROBE");
    expect(approval.target_uri).toBe("http://127.0.0.1:8088/api/v1/debug/config");
  });

  it("stores vulnerability finding on 'finding_recorded'", () => {
    eventBus.dispatch({
      seq_num: 6,
      event_type: "finding_recorded",
      correlation_id: "corr-04",
      agent_id: "agent-vuln-01",
      engagement_id: "eng-mvp-001",
      timestamp_utc: new Date().toISOString(),
      payload: {
        finding_id: "FINDING-001",
        title: "Unauthenticated Sensitive Configuration Exposure",
        severity: "HIGH",
        cvss_score: 7.5,
        cwe_id: "CWE-200",
        target_endpoint: "http://127.0.0.1:8088/api/v1/debug/config",
      },
    });

    const finding = useEventStore.getState().findings["FINDING-001"];
    expect(finding).toBeDefined();
    expect(finding.severity).toBe("HIGH");
    expect(finding.cvss_score).toBe(7.5);
    expect(finding.cwe_id).toBe("CWE-200");
  });

  it("halts all agents on 'kill_switch_tripped'", () => {
    // Populate two running agents
    useEventStore.getState().upsertAgent({
      agent_id: "agent-01",
      name: "Agent 1",
      role: "role_web_discovery",
      department: "dept_recon",
      state: "EXECUTING",
      x: 0,
      y: 0,
    });
    useEventStore.getState().upsertAgent({
      agent_id: "agent-02",
      name: "Agent 2",
      role: "role_web_vuln_assessor",
      department: "dept_vulnerability",
      state: "PLANNING",
      x: 0,
      y: 0,
    });

    eventBus.dispatch({
      seq_num: 7,
      event_type: "kill_switch_tripped",
      correlation_id: "corr-kill",
      timestamp_utc: new Date().toISOString(),
      payload: {},
    });

    expect(useEventStore.getState().agents["agent-01"].state).toBe("EMERGENCY_HALTED");
    expect(useEventStore.getState().agents["agent-02"].state).toBe("EMERGENCY_HALTED");
  });

  it("invokes custom subscribers registered with eventBus.on()", () => {
    const customCallback = vi.fn();
    const unsubscribe = eventBus.on("custom_scan_event", customCallback);

    eventBus.dispatch({
      seq_num: 8,
      event_type: "custom_scan_event",
      correlation_id: "corr-custom",
      timestamp_utc: new Date().toISOString(),
      payload: { custom_val: 123 },
    });

    expect(customCallback).toHaveBeenCalledTimes(1);
    unsubscribe();

    // After unsubscribe, should not fire
    eventBus.dispatch({
      seq_num: 9,
      event_type: "custom_scan_event",
      correlation_id: "corr-custom-2",
      timestamp_utc: new Date().toISOString(),
      payload: { custom_val: 456 },
    });

    expect(customCallback).toHaveBeenCalledTimes(1);
  });
});
