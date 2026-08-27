"""Unit tests for AgentStateMachine FSM transitions, state validation, and error handling."""

import pytest
from app.agents.state_machine import (
    AgentLifecycleState,
    AgentStateMachine,
    InvalidStateTransitionError,
)


def test_agent_fsm_standard_happy_path():
    fsm = AgentStateMachine(agent_id="agent-recon-01")
    assert fsm.current_state == AgentLifecycleState.IDLE

    # 1. Assign Task -> ASSIGNED
    rec1 = fsm.assign_task(task_id="TASK_01")
    assert fsm.current_state == AgentLifecycleState.ASSIGNED
    assert rec1.from_state == AgentLifecycleState.IDLE
    assert rec1.to_state == AgentLifecycleState.ASSIGNED

    # 2. Preparing Workspace -> PREPARING
    fsm.start_preparing()
    assert fsm.current_state == AgentLifecycleState.PREPARING

    # 3. Running Subprocess -> RUNNING
    fsm.start_running()
    assert fsm.current_state == AgentLifecycleState.RUNNING

    # 4. Reviewing Findings -> REVIEW
    fsm.enter_review()
    assert fsm.current_state == AgentLifecycleState.REVIEW

    # 5. Mark Completed -> COMPLETED
    fsm.mark_completed()
    assert fsm.current_state == AgentLifecycleState.COMPLETED

    # 6. Reset to IDLE for next task
    fsm.transition_to(AgentLifecycleState.IDLE)
    assert fsm.current_state == AgentLifecycleState.IDLE
    assert len(fsm.history) == 6


def test_agent_fsm_approval_gate_flow():
    fsm = AgentStateMachine(agent_id="agent-vuln-01")

    # Move to RUNNING
    fsm.transition_to(AgentLifecycleState.ASSIGNED)
    fsm.transition_to(AgentLifecycleState.PREPARING)
    fsm.transition_to(AgentLifecycleState.RUNNING)

    # Encounter approval gate -> WAITING_BLOCKED
    fsm.wait_for_approval(gate_id="gate-001")
    assert fsm.current_state == AgentLifecycleState.WAITING_BLOCKED

    # Approval granted by operator -> Resume RUNNING
    fsm.start_running()
    assert fsm.current_state == AgentLifecycleState.RUNNING

    # Finish task
    fsm.transition_to(AgentLifecycleState.REVIEW)
    fsm.mark_completed()
    assert fsm.current_state == AgentLifecycleState.COMPLETED


def test_agent_fsm_error_and_recovery_loop():
    fsm = AgentStateMachine(agent_id="agent-exploit-01")

    # Move to RUNNING
    fsm.transition_to(AgentLifecycleState.ASSIGNED)
    fsm.transition_to(AgentLifecycleState.PREPARING)
    fsm.transition_to(AgentLifecycleState.RUNNING)

    # Subprocess fails -> FAILED
    fsm.mark_failed(error_message="Socket timeout on target")
    assert fsm.current_state == AgentLifecycleState.FAILED

    # Enter RECOVERY
    fsm.start_recovery()
    assert fsm.current_state == AgentLifecycleState.RECOVERY

    # Re-attempt preparation -> PREPARING -> RUNNING
    fsm.start_preparing()
    assert fsm.current_state == AgentLifecycleState.PREPARING
    fsm.start_running()
    assert fsm.current_state == AgentLifecycleState.RUNNING


def test_agent_fsm_illegal_transitions_raise_error():
    fsm = AgentStateMachine(agent_id="agent-test-01")

    # 1. IDLE -> COMPLETED is illegal
    with pytest.raises(InvalidStateTransitionError) as exc1:
        fsm.transition_to(AgentLifecycleState.COMPLETED)
    assert "cannot transition from 'idle' to 'completed'" in str(exc1.value)

    # 2. IDLE -> RUNNING is illegal (must prepare first)
    with pytest.raises(InvalidStateTransitionError):
        fsm.transition_to(AgentLifecycleState.RUNNING)

    # Advance to PREPARING
    fsm.transition_to(AgentLifecycleState.ASSIGNED)
    fsm.transition_to(AgentLifecycleState.PREPARING)

    # 3. PREPARING -> COMPLETED is illegal
    with pytest.raises(InvalidStateTransitionError):
        fsm.transition_to(AgentLifecycleState.COMPLETED)

    # Advance to COMPLETED
    fsm.transition_to(AgentLifecycleState.RUNNING)
    fsm.transition_to(AgentLifecycleState.COMPLETED)

    # 4. COMPLETED -> RUNNING is illegal (must return to IDLE or PLANNING)
    with pytest.raises(InvalidStateTransitionError):
        fsm.transition_to(AgentLifecycleState.RUNNING)


def test_agent_fsm_emergency_termination_from_any_state():
    # Can terminate from RUNNING
    fsm1 = AgentStateMachine(agent_id="agent-01")
    fsm1.transition_to(AgentLifecycleState.ASSIGNED)
    fsm1.transition_to(AgentLifecycleState.PREPARING)
    fsm1.transition_to(AgentLifecycleState.RUNNING)
    fsm1.terminate(reason="global_kill_switch")
    assert fsm1.current_state == AgentLifecycleState.TERMINATION

    # Can terminate from WAITING_BLOCKED
    fsm2 = AgentStateMachine(agent_id="agent-02")
    fsm2.transition_to(AgentLifecycleState.ASSIGNED)
    fsm2.transition_to(AgentLifecycleState.WAITING_BLOCKED)
    fsm2.terminate(reason="engagement_cancelled")
    assert fsm2.current_state == AgentLifecycleState.TERMINATION


def test_agent_fsm_transition_callback():
    callback_calls = []

    def on_trans(record):
        callback_calls.append(record)

    fsm = AgentStateMachine(agent_id="agent-cb-01", on_transition=on_trans)
    fsm.assign_task("TASK_99")

    assert len(callback_calls) == 1
    assert callback_calls[0].from_state == AgentLifecycleState.IDLE
    assert callback_calls[0].to_state == AgentLifecycleState.ASSIGNED
