"""Unit tests for TaskStateMachine FSM transitions, state validation, DAG readiness computation, and error handling."""

import pytest
from app.tasks.state_machine import (
    ALLOWED_TASK_TRANSITIONS,
    InvalidTaskStateTransitionError,
    TaskLifecycleState,
    TaskStateMachine,
)


def test_task_fsm_standard_happy_path():
    """Verify standard happy-path progression from PENDING through REVIEW to COMPLETED."""
    fsm = TaskStateMachine(task_id="task-recon-01")
    assert fsm.current_state == TaskLifecycleState.PENDING
    assert fsm.assigned_agent_id is None

    # 1. Dependencies satisfied -> READY
    rec1 = fsm.mark_ready()
    assert fsm.current_state == TaskLifecycleState.READY
    assert rec1.from_state == TaskLifecycleState.PENDING
    assert rec1.to_state == TaskLifecycleState.READY

    # 2. Assign agent -> ASSIGNED
    rec2 = fsm.assign_agent(agent_id="agent-recon-01")
    assert fsm.current_state == TaskLifecycleState.ASSIGNED
    assert fsm.assigned_agent_id == "agent-recon-01"
    assert rec2.from_state == TaskLifecycleState.READY
    assert rec2.to_state == TaskLifecycleState.ASSIGNED

    # 3. Start execution -> IN_PROGRESS
    rec3 = fsm.start_progress()
    assert fsm.current_state == TaskLifecycleState.IN_PROGRESS
    assert rec3.from_state == TaskLifecycleState.ASSIGNED
    assert rec3.to_state == TaskLifecycleState.IN_PROGRESS

    # 4. Submit findings -> REVIEW
    rec4 = fsm.enter_review()
    assert fsm.current_state == TaskLifecycleState.REVIEW
    assert rec4.from_state == TaskLifecycleState.IN_PROGRESS
    assert rec4.to_state == TaskLifecycleState.REVIEW

    # 5. CISO approves -> COMPLETED
    rec5 = fsm.mark_completed()
    assert fsm.current_state == TaskLifecycleState.COMPLETED
    assert rec5.from_state == TaskLifecycleState.REVIEW
    assert rec5.to_state == TaskLifecycleState.COMPLETED
    assert len(fsm.history) == 5


def test_task_fsm_approval_gating_and_unblocking_flow():
    """Verify approval gating pauses execution in BLOCKED state and resumes to IN_PROGRESS upon approval."""
    fsm = TaskStateMachine(
        task_id="task-exploit-01", initial_state=TaskLifecycleState.READY
    )

    fsm.assign_agent("agent-exploit-01")
    fsm.start_progress()
    assert fsm.current_state == TaskLifecycleState.IN_PROGRESS

    # Encounter high-risk tool approval gate -> BLOCKED
    rec_block = fsm.block(
        reason="Active exploit payload requires human operator approval",
        gate_id="gate-exp-01",
    )
    assert fsm.current_state == TaskLifecycleState.BLOCKED
    assert rec_block.metadata["gate_id"] == "gate-exp-01"

    # Human grants approval -> Unblock to IN_PROGRESS
    rec_unblock = fsm.unblock()
    assert fsm.current_state == TaskLifecycleState.IN_PROGRESS
    assert rec_unblock.from_state == TaskLifecycleState.BLOCKED
    assert rec_unblock.to_state == TaskLifecycleState.IN_PROGRESS

    # Complete task
    fsm.mark_completed()
    assert fsm.current_state == TaskLifecycleState.COMPLETED


def test_task_fsm_review_rejection_and_rework_flow():
    """Verify finding review rejection routes task back to IN_PROGRESS for rework before final completion."""
    fsm = TaskStateMachine(
        task_id="task-vuln-01", initial_state=TaskLifecycleState.READY
    )
    fsm.assign_agent("agent-vuln-01")
    fsm.start_progress()
    fsm.enter_review()
    assert fsm.current_state == TaskLifecycleState.REVIEW

    # CISO rejects draft finding for lack of proof -> Return to IN_PROGRESS for rework
    fsm.transition_to(
        TaskLifecycleState.IN_PROGRESS,
        trigger="rework_requested",
        metadata={"feedback": "Missing raw HTTP response artifact in evidence"},
    )
    assert fsm.current_state == TaskLifecycleState.IN_PROGRESS

    # Resubmit and approve
    fsm.enter_review()
    fsm.mark_completed()
    assert fsm.current_state == TaskLifecycleState.COMPLETED


def test_task_fsm_failure_and_tactical_replan_retry():
    """Verify task failure can be tactically replanned and returned to READY for re-execution."""
    fsm = TaskStateMachine(
        task_id="task-portscan-01", initial_state=TaskLifecycleState.READY
    )
    fsm.assign_agent("agent-recon-01")
    fsm.start_progress()

    # Subprocess execution fails permanently after retries -> FAILED
    fsm.mark_failed(reason="Target host rate-limited and closed connections")
    assert fsm.current_state == TaskLifecycleState.FAILED

    # CISO triggers tactical replan -> Return to READY
    fsm.transition_to(TaskLifecycleState.READY, trigger="ciso_replan_reschedule")
    assert fsm.current_state == TaskLifecycleState.READY

    # Re-assign and complete successfully
    fsm.assign_agent("agent-recon-02")
    fsm.start_progress()
    fsm.mark_completed()
    assert fsm.current_state == TaskLifecycleState.COMPLETED


def test_task_fsm_evaluate_readiness_from_dag():
    """Technical Decision: Verify 'ready' state is computed from dependency graph satisfaction."""
    fsm = TaskStateMachine(
        task_id="task-vuln-scan-01", initial_state=TaskLifecycleState.PENDING
    )

    dependencies = ["task-recon-01", "task-recon-02"]

    # 1. Partial completion -> Not ready, stays PENDING
    completed_partial = {"task-recon-01"}
    is_ready_partial = fsm.evaluate_readiness(
        completed_task_ids=completed_partial,
        dependency_task_ids=dependencies,
    )
    assert is_ready_partial is False
    assert fsm.current_state == TaskLifecycleState.PENDING

    # 2. All completed -> Transitions to READY
    completed_all = {"task-recon-01", "task-recon-02", "other-task-99"}
    is_ready_full = fsm.evaluate_readiness(
        completed_task_ids=completed_all,
        dependency_task_ids=dependencies,
    )
    assert is_ready_full is True
    assert fsm.current_state == TaskLifecycleState.READY
    assert len(fsm.history) == 1
    assert fsm.history[0].trigger == "dependencies_satisfied"


def test_task_fsm_operator_cancellation():
    """Verify task can be cancelled from various active and pending states."""
    # From PENDING
    fsm1 = TaskStateMachine(task_id="task-01", initial_state=TaskLifecycleState.PENDING)
    fsm1.cancel(reason="scope_reduced")
    assert fsm1.current_state == TaskLifecycleState.CANCELLED

    # From IN_PROGRESS
    fsm2 = TaskStateMachine(task_id="task-02", initial_state=TaskLifecycleState.READY)
    fsm2.assign_agent("agent-01")
    fsm2.start_progress()
    fsm2.cancel(reason="emergency_kill")
    assert fsm2.current_state == TaskLifecycleState.CANCELLED

    # From BLOCKED
    fsm3 = TaskStateMachine(task_id="task-03", initial_state=TaskLifecycleState.READY)
    fsm3.assign_agent("agent-01")
    fsm3.start_progress()
    fsm3.block(reason="awaiting approval")
    fsm3.cancel(reason="engagement_aborted")
    assert fsm3.current_state == TaskLifecycleState.CANCELLED


def test_task_fsm_illegal_transitions_raise_error():
    """Acceptance Criteria: Verify illegal state jumps are strictly rejected."""
    fsm = TaskStateMachine(
        task_id="task-strict-01", initial_state=TaskLifecycleState.PENDING
    )

    # 1. PENDING -> COMPLETED is illegal (must run first)
    with pytest.raises(InvalidTaskStateTransitionError) as exc1:
        fsm.transition_to(TaskLifecycleState.COMPLETED)
    assert "cannot transition from 'pending' to 'completed'" in str(exc1.value)

    # 2. PENDING -> IN_PROGRESS is illegal (must be ready and assigned first)
    with pytest.raises(InvalidTaskStateTransitionError):
        fsm.transition_to(TaskLifecycleState.IN_PROGRESS)

    # 3. PENDING -> REVIEW is illegal
    with pytest.raises(InvalidTaskStateTransitionError):
        fsm.transition_to(TaskLifecycleState.REVIEW)

    # Advance to READY
    fsm.mark_ready()

    # 4. READY -> COMPLETED is illegal
    with pytest.raises(InvalidTaskStateTransitionError):
        fsm.transition_to(TaskLifecycleState.COMPLETED)

    # Advance to ASSIGNED -> IN_PROGRESS -> BLOCKED
    fsm.assign_agent("agent-01")
    fsm.start_progress()
    fsm.block(reason="gate")

    # 5. BLOCKED -> COMPLETED is illegal (must unblock first)
    with pytest.raises(InvalidTaskStateTransitionError):
        fsm.transition_to(TaskLifecycleState.COMPLETED)


def test_task_fsm_transition_callback():
    """Verify registered transition callbacks are invoked with transition records."""
    emitted_records = []

    def on_trans(rec):
        emitted_records.append(rec)

    fsm = TaskStateMachine(
        task_id="task-cb-01",
        initial_state=TaskLifecycleState.READY,
        on_transition=on_trans,
    )
    fsm.assign_agent("agent-recon-01")
    fsm.start_progress()

    assert len(emitted_records) == 2
    assert emitted_records[0].from_state == TaskLifecycleState.READY
    assert emitted_records[0].to_state == TaskLifecycleState.ASSIGNED
    assert emitted_records[0].assigned_agent_id == "agent-recon-01"
    assert emitted_records[1].from_state == TaskLifecycleState.ASSIGNED
    assert emitted_records[1].to_state == TaskLifecycleState.IN_PROGRESS


def test_task_fsm_case_insensitive_and_alias_lookups():
    """Verify case-insensitive string lookups and status aliases resolve cleanly."""
    assert TaskLifecycleState("READY") == TaskLifecycleState.READY
    assert TaskLifecycleState("running") == TaskLifecycleState.IN_PROGRESS
    assert TaskLifecycleState("awaiting_approval") == TaskLifecycleState.BLOCKED
    assert TaskLifecycleState("canceled") == TaskLifecycleState.CANCELLED
    assert TaskLifecycleState("in_progress") == TaskLifecycleState.IN_PROGRESS


def test_allowed_task_transitions_table_completeness():
    """Verify all defined TaskLifecycleState members exist in ALLOWED_TASK_TRANSITIONS."""
    for state in TaskLifecycleState:
        assert state in ALLOWED_TASK_TRANSITIONS
        assert isinstance(ALLOWED_TASK_TRANSITIONS[state], set)
