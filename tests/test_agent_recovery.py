"""Unit and integration tests for Agent Failure Classification, Exponential Backoff, and Recovery/Escalation logic."""

import asyncio

import pytest
from app.agents.events import AgentLifecycleService
from app.agents.recovery import (
    AgentRecoveryService,
    FailureClassification,
    FailureType,
    RecoveryAbandonedError,
    RecoveryAction,
    RecoveryEscalatedError,
    RecoveryPolicy,
    RecoveryPolicyRule,
)
from app.agents.state_machine import AgentLifecycleState
from app.ciso.monitor import CisoProgressMonitor
from app.domain.engagement import Base, EngagementCreateRequest
from app.domain.task import TaskCreateRequest, TaskStatus
from app.orchestrator import global_orchestrator
from app.repositories.unit_of_work import UnitOfWork
from app.services.org_bootstrap import OrgBootstrapService
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def setup_test_environment():
    """Create in-memory SQLite database, tables, and seeded organization for recovery tests."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    bootstrap = OrgBootstrapService(session_factory)
    await bootstrap.bootstrap_organization()

    async with UnitOfWork(session_factory) as uow:
        await uow.engagements.create_engagement(
            EngagementCreateRequest(
                engagement_id="eng-rec-test",
                title="Recovery Test Engagement",
                organization="TargetCorp",
                authorized_by="CISO",
            )
        )
        await uow.tasks.create_task(
            TaskCreateRequest(
                task_id="TASK_PROBE_01",
                engagement_id="eng-rec-test",
                department_id="dept_recon",
                title="Active Port Probe",
                assigned_role="role_web_discovery",
                assigned_agent_id="agent-recon-01",
            )
        )
        await uow.commit()

    return session_factory, engine


def test_failure_classification_by_exception_type():
    """Verify built-in Python exceptions map accurately to transient vs terminal failure types."""
    policy = RecoveryPolicy()

    # Transient exceptions
    f_type, f_class = policy.classify_failure(TimeoutError("Connection timed out"))
    assert f_type in (FailureType.TOOL_TIMEOUT, FailureType.NETWORK_TIMEOUT)
    assert f_class == FailureClassification.TRANSIENT

    f_type, f_class = policy.classify_failure(
        ConnectionResetError("Connection reset by peer")
    )
    assert f_type == FailureType.NETWORK_CONNECTION_ERROR
    assert f_class == FailureClassification.TRANSIENT

    # Terminal exceptions
    f_type, f_class = policy.classify_failure(
        PermissionError("Access to raw socket denied")
    )
    assert f_type == FailureType.PERMISSION_DENIED
    assert f_class == FailureClassification.TERMINAL

    f_type, f_class = policy.classify_failure(
        FileNotFoundError("nmap binary not found")
    )
    assert f_type == FailureType.COMMAND_NOT_FOUND
    assert f_class == FailureClassification.TERMINAL

    f_type, f_class = policy.classify_failure(
        ValueError("Target 10.0.0.99 is out of authorized scope")
    )
    assert f_type == FailureType.SCOPE_VIOLATION
    assert f_class == FailureClassification.TERMINAL


def test_failure_classification_by_exit_code_and_strings():
    """Verify exit codes and regex patterns classify failures properly."""
    policy = RecoveryPolicy()

    # Exit code 127 = Command Not Found (Terminal)
    f_type, f_class = policy.classify_failure("some error", exit_code=127)
    assert f_type == FailureType.COMMAND_NOT_FOUND
    assert f_class == FailureClassification.TERMINAL

    # Exit code 126 = Permission Denied (Terminal)
    f_type, f_class = policy.classify_failure("executable error", exit_code=126)
    assert f_type == FailureType.PERMISSION_DENIED
    assert f_class == FailureClassification.TERMINAL

    # Rate limiting 429 string (Transient)
    f_type, f_class = policy.classify_failure(
        "HTTP error 429: Too Many Requests from API provider"
    )
    assert f_type == FailureType.RATE_LIMITED
    assert f_class == FailureClassification.TRANSIENT

    # Approval rejected (Terminal)
    f_type, f_class = policy.classify_failure(
        "Action declined: approval rejected by operator"
    )
    assert f_type == FailureType.APPROVAL_REJECTED
    assert f_class == FailureClassification.TERMINAL


def test_exponential_backoff_calculation():
    """Verify exponential backoff calculation matches expected delay curve and caps."""
    policy = RecoveryPolicy()
    rule = RecoveryPolicyRule(
        failure_type=FailureType.TOOL_TIMEOUT,
        classification=FailureClassification.TRANSIENT,
        is_retryable=True,
        max_retries=4,
        base_delay_seconds=1.5,
        backoff_factor=2.0,
        max_delay_seconds=10.0,
    )

    # Attempt 1: 1.5 * (2^0) = 1.5s
    assert policy.compute_backoff_delay(1, rule) == 1.5

    # Attempt 2: 1.5 * (2^1) = 3.0s
    assert policy.compute_backoff_delay(2, rule) == 3.0

    # Attempt 3: 1.5 * (2^2) = 6.0s
    assert policy.compute_backoff_delay(3, rule) == 6.0

    # Attempt 4: 1.5 * (2^3) = 12.0s -> Capped at max_delay_seconds 10.0s
    assert policy.compute_backoff_delay(4, rule) == 10.0


def test_policy_evaluation_decisions():
    """Verify evaluate_recovery produces RETRY, ESCALATE, or ABANDON based on retry counts."""
    policy = RecoveryPolicy()

    # 1. Transient failure with retries remaining -> RETRY
    dec1 = policy.evaluate_recovery(
        failure=TimeoutError("Probe timeout"),
        current_retry_count=0,
    )
    assert dec1.action == RecoveryAction.RETRY
    assert dec1.classification == FailureClassification.TRANSIENT
    assert dec1.retry_count == 1
    assert dec1.delay_seconds > 0.0

    # 2. Transient failure with retries exhausted (current_retry_count >= max_retries) -> ESCALATE
    dec2 = policy.evaluate_recovery(
        failure=TimeoutError("Probe timeout"),
        current_retry_count=3,
    )
    assert dec2.action == RecoveryAction.ESCALATE
    assert dec2.escalated_to == "ciso_monitor"
    assert dec2.delay_seconds == 0.0

    # 3. Terminal failure (Permission Denied) -> ESCALATE immediately
    dec3 = policy.evaluate_recovery(
        failure=PermissionError("Scope restriction violation"),
        current_retry_count=0,
    )
    assert dec3.action == RecoveryAction.ESCALATE
    assert dec3.classification == FailureClassification.TERMINAL
    assert dec3.max_retries == 0

    # 4. Approval Rejected -> ABANDON
    dec4 = policy.evaluate_recovery(
        failure="approval rejected by user",
        current_retry_count=0,
    )
    assert dec4.action == RecoveryAction.ABANDON


@pytest.mark.asyncio
async def test_agent_recovery_transient_retry_and_success_flow():
    """Acceptance Criteria: Transient failure retries with backoff and succeeds in execution."""
    session_factory, engine = await setup_test_environment()
    try:
        lifecycle_service = AgentLifecycleService(session_factory)
        recovery_service = AgentRecoveryService(
            session_factory=session_factory,
            lifecycle_service=lifecycle_service,
        )

        # Set initial agent state to RUNNING
        await lifecycle_service.transition_agent_state(
            agent_id="agent-recon-01",
            target_state=AgentLifecycleState.ASSIGNED,
            task_id="TASK_PROBE_01",
        )
        await lifecycle_service.transition_agent_state(
            agent_id="agent-recon-01",
            target_state=AgentLifecycleState.PREPARING,
            task_id="TASK_PROBE_01",
        )
        await lifecycle_service.transition_agent_state(
            agent_id="agent-recon-01",
            target_state=AgentLifecycleState.RUNNING,
            task_id="TASK_PROBE_01",
        )

        attempts = 0
        sleep_delays: list[float] = []

        async def mock_sleep(delay: float):
            sleep_delays.append(delay)

        async def flaky_task():
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise TimeoutError(f"Network timeout on probe attempt {attempts}")
            return {"status": "success", "open_ports": [80, 443]}

        # Execute with recovery
        result = await recovery_service.execute_with_recovery(
            coro_func=flaky_task,
            agent_id="agent-recon-01",
            task_id="TASK_PROBE_01",
            engagement_id="eng-rec-test",
            sleep_func=mock_sleep,
        )

        assert result["status"] == "success"
        assert result["open_ports"] == [80, 443]
        assert attempts == 3
        # Should have executed 2 backoff delays
        assert len(sleep_delays) == 2
        assert sleep_delays[0] > 0.0
        assert sleep_delays[1] >= sleep_delays[0]

        # Verify retry counter was reset on success
        assert recovery_service.get_retry_count("agent-recon-01", "TASK_PROBE_01") == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_agent_recovery_terminal_failure_escalates_after_cap():
    """Acceptance Criteria: Failure exceeding retry cap escalates to CISO monitor and fails task."""
    session_factory, engine = await setup_test_environment()
    try:
        lifecycle_service = AgentLifecycleService(session_factory)
        ciso_monitor = CisoProgressMonitor(session_factory)
        recovery_service = AgentRecoveryService(
            session_factory=session_factory,
            lifecycle_service=lifecycle_service,
            ciso_monitor=ciso_monitor,
        )

        # Move agent to RUNNING
        await lifecycle_service.transition_agent_state(
            agent_id="agent-recon-01",
            target_state=AgentLifecycleState.ASSIGNED,
            task_id="TASK_PROBE_01",
        )
        await lifecycle_service.transition_agent_state(
            agent_id="agent-recon-01",
            target_state=AgentLifecycleState.PREPARING,
            task_id="TASK_PROBE_01",
        )
        await lifecycle_service.transition_agent_state(
            agent_id="agent-recon-01",
            target_state=AgentLifecycleState.RUNNING,
            task_id="TASK_PROBE_01",
        )

        captured_events = []

        async def event_collector(event):
            captured_events.append(event)

        global_orchestrator.register_event_subscriber(event_collector)
        await global_orchestrator.start()

        attempts = 0

        async def always_failing_task():
            nonlocal attempts
            attempts += 1
            raise TimeoutError(f"Persistent timeout on attempt {attempts}")

        # Execute with max 2 retries
        with pytest.raises(RecoveryEscalatedError) as exc_info:
            await recovery_service.execute_with_recovery(
                coro_func=always_failing_task,
                agent_id="agent-recon-01",
                task_id="TASK_PROBE_01",
                engagement_id="eng-rec-test",
                custom_max_retries=2,
                sleep_func=lambda d: asyncio.sleep(0.001),  # fast sleep
            )

        assert "escalated to 'ciso_monitor'" in str(exc_info.value)
        assert attempts == 3  # Initial try + 2 retries = 3 attempts total

        await asyncio.sleep(0.05)
        await global_orchestrator.stop()

        # Verify task status in database was marked FAILED
        async with UnitOfWork(session_factory) as uow:
            task = await uow.tasks.get_by_id("TASK_PROBE_01")
            assert task is not None
            assert task.status == TaskStatus.FAILED

        # Verify emitted events contain task_failed and agent_recovery_escalated
        event_types = [e.event_type for e in captured_events]
        assert "agent_recovery_attempted" in event_types
        assert "agent_recovery_escalated" in event_types
        assert "task_failed" in event_types
    finally:
        global_orchestrator.unregister_event_subscriber(event_collector)
        await engine.dispose()


@pytest.mark.asyncio
async def test_agent_recovery_immediate_terminal_scope_violation():
    """Verify terminal scope violation escalates immediately without wasting retry cycles."""
    session_factory, engine = await setup_test_environment()
    try:
        lifecycle_service = AgentLifecycleService(session_factory)
        ciso_monitor = CisoProgressMonitor(session_factory)
        recovery_service = AgentRecoveryService(
            session_factory=session_factory,
            lifecycle_service=lifecycle_service,
            ciso_monitor=ciso_monitor,
        )

        await lifecycle_service.transition_agent_state(
            agent_id="agent-recon-01",
            target_state=AgentLifecycleState.ASSIGNED,
            task_id="TASK_PROBE_01",
        )
        await lifecycle_service.transition_agent_state(
            agent_id="agent-recon-01",
            target_state=AgentLifecycleState.PREPARING,
            task_id="TASK_PROBE_01",
        )
        await lifecycle_service.transition_agent_state(
            agent_id="agent-recon-01",
            target_state=AgentLifecycleState.RUNNING,
            task_id="TASK_PROBE_01",
        )

        attempts = 0

        async def scope_violation_task():
            nonlocal attempts
            attempts += 1
            raise ValueError("Target IP 192.168.1.50 is a scope violation (ROE denied)")

        with pytest.raises(RecoveryEscalatedError) as exc_info:
            await recovery_service.execute_with_recovery(
                coro_func=scope_violation_task,
                agent_id="agent-recon-01",
                task_id="TASK_PROBE_01",
                engagement_id="eng-rec-test",
            )

        # Must execute exactly once (0 retries)
        assert attempts == 1
        assert exc_info.value.decision.classification == FailureClassification.TERMINAL
        assert exc_info.value.decision.failure_type == FailureType.SCOPE_VIOLATION
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_agent_recovery_approval_rejected_abandon_flow():
    """Verify operator rejection triggers immediate abandonment without retry or DAG replan."""
    session_factory, engine = await setup_test_environment()
    try:
        lifecycle_service = AgentLifecycleService(session_factory)
        recovery_service = AgentRecoveryService(
            session_factory=session_factory,
            lifecycle_service=lifecycle_service,
        )

        async def rejected_task():
            raise RuntimeError("approval rejected by operator")

        with pytest.raises(RecoveryAbandonedError) as exc_info:
            await recovery_service.execute_with_recovery(
                coro_func=rejected_task,
                agent_id="agent-recon-01",
                task_id="TASK_PROBE_01",
                engagement_id="eng-rec-test",
            )

        assert "Agent execution abandoned" in str(exc_info.value)
        assert exc_info.value.decision.action == RecoveryAction.ABANDON

        # Verify task is cancelled
        async with UnitOfWork(session_factory) as uow:
            task = await uow.tasks.get_by_id("TASK_PROBE_01")
            assert task is not None
            assert task.status == TaskStatus.CANCELLED
    finally:
        await engine.dispose()
