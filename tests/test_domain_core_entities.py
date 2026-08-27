"""Unit tests for Message, Command/Execution, Approval, and Immutable AuditEvent domain models."""

import pytest
from app.domain.agent import AgentCreateRequest, AgentStatus, AIEmployeeRepository
from app.domain.approval import (
    ApprovalDecisionRequest,
    ApprovalRepository,
    ApprovalRequestSchema,
    ApprovalStatus,
)
from app.domain.audit import (
    AuditEventCreateRequest,
    ImmutableAuditEventRepository,
    ImmutableAuditViolationError,
)
from app.domain.communication import (
    MessageCreateRequest,
    MessageRepository,
    MessageType,
)
from app.domain.department import DepartmentCreateRequest, DepartmentRepository
from app.domain.engagement import (
    Base,
    EngagementCreateRequest,
    EngagementRepository,
)
from app.domain.execution import (
    CommandRecordSchema,
    ExecutionCreateRequest,
    ExecutionRepository,
)
from app.domain.role import RoleCreateRequest, RoleRepository
from app.domain.task import TaskCreateRequest, TaskRepository
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.mark.asyncio
async def test_communication_execution_and_approval_entities():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    dept_repo = DepartmentRepository(session_factory=session_factory)
    role_repo = RoleRepository(session_factory=session_factory)
    eng_repo = EngagementRepository(session_factory=session_factory)
    agent_repo = AIEmployeeRepository(session_factory=session_factory)
    task_repo = TaskRepository(session_factory=session_factory)
    msg_repo = MessageRepository(session_factory=session_factory)
    exec_repo = ExecutionRepository(session_factory=session_factory)
    appr_repo = ApprovalRepository(session_factory=session_factory)

    # 1. Seed Parent Data
    await dept_repo.upsert(DepartmentCreateRequest(id="dept_recon", name="Recon"))
    await role_repo.upsert(
        RoleCreateRequest(
            id="role_recon",
            name="Recon Role",
            department_id="dept_recon",
            system_prompt_template="tpl",
        )
    )
    await eng_repo.create(
        EngagementCreateRequest(
            engagement_id="eng-core-01",
            title="Core Test",
            organization="Acme",
            authorized_by="CISO",
        )
    )
    await agent_repo.create(
        AgentCreateRequest(
            id="agent-01",
            role_id="role_recon",
            department_id="dept_recon",
            display_name="Agent 1",
            status=AgentStatus.EXECUTING,
        )
    )
    await agent_repo.create(
        AgentCreateRequest(
            id="agent-02",
            role_id="role_recon",
            department_id="dept_recon",
            display_name="Agent 2",
            status=AgentStatus.IDLE,
        )
    )
    await task_repo.create_task(
        TaskCreateRequest(
            task_id="TASK-01",
            engagement_id="eng-core-01",
            department_id="dept_recon",
            title="Recon Target",
            assigned_role="role_recon",
        )
    )

    # 2. Test Agent Message Creation
    msg = await msg_repo.send_message(
        MessageCreateRequest(
            id="msg-001",
            engagement_id="eng-core-01",
            sender_agent_id="agent-01",
            recipient_agent_id="agent-02",
            task_id="TASK-01",
            message_type=MessageType.TASK_HANDOFF,
            content="Reconnaissance phase completed. Ready for vulnerability assessment.",
            metadata={"discovered_ports": [80, 8088]},
        )
    )
    assert msg.id == "msg-001"
    assert msg.message_type == MessageType.TASK_HANDOFF
    assert msg.metadata["discovered_ports"] == [80, 8088]

    task_msgs = await msg_repo.list_by_task("TASK-01")
    assert len(task_msgs) == 1

    # 3. Test Process Execution Record
    exec_record = await exec_repo.record_execution(
        ExecutionCreateRequest(
            id="exec-001",
            engagement_id="eng-core-01",
            task_id="TASK-01",
            agent_id="agent-01",
            workspace_path="/data/workspaces/agent-01",
            pid=1024,
            exit_code=0,
            stdout_artifact_path="/data/evidence/nmap.xml",
            duration_sec=1.45,
            command=CommandRecordSchema(
                raw_command="nmap -sV -p 8088 127.0.0.1",
                sanitized_command="nmap -sV -p 8088 127.0.0.1",
                target="127.0.0.1:8088",
                tool_name="nmap",
            ),
        )
    )
    assert exec_record.id == "exec-001"
    assert exec_record.exit_code == 0
    assert exec_record.command.tool_name == "nmap"

    # 4. Test Approval Gate Lifecycle
    appr_req = await appr_repo.create_request(
        ApprovalRequestSchema(
            id="gate-001",
            engagement_id="eng-core-01",
            task_id="TASK-01",
            agent_id="agent-01",
            category="ACTIVE_EXPLOITATION_PROBE",
            target_uri="http://127.0.0.1:8088/api/v1/debug/config",
            risk_description="Verify secret leakage on unauthenticated endpoint",
            proposed_command="curl -s http://127.0.0.1:8088/api/v1/debug/config",
        )
    )
    assert appr_req.id == "gate-001"
    assert appr_req.status == ApprovalStatus.PENDING

    pending = await appr_repo.list_pending("eng-core-01")
    assert len(pending) == 1

    # Decide Gate
    decided = await appr_repo.decide_gate(
        "gate-001",
        ApprovalDecisionRequest(
            decision=ApprovalStatus.GRANTED,
            operator_id="operator-01",
            decision_reason="Approved for controlled lab verification",
        ),
    )
    assert decided is not None
    assert decided.status == ApprovalStatus.GRANTED
    assert decided.operator_id == "operator-01"

    pending_after = await appr_repo.list_pending("eng-core-01")
    assert len(pending_after) == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_immutable_audit_events_and_hash_chaining():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    eng_repo = EngagementRepository(session_factory=session_factory)
    audit_repo = ImmutableAuditEventRepository(session_factory=session_factory)

    await eng_repo.create(
        EngagementCreateRequest(
            engagement_id="eng-audit-01",
            title="Audit Test",
            organization="Org",
            authorized_by="CISO",
        )
    )

    # 1. Append Audit Event 1 (Genesis Event)
    ev1 = await audit_repo.append(
        AuditEventCreateRequest(
            event_id="ev-01",
            engagement_id="eng-audit-01",
            correlation_id="corr-audit-01",
            event_type="engagement_started",
            actor_type="OPERATOR",
            actor_id="operator-01",
            payload={"authorized": True},
        )
    )
    assert ev1.seq == 1
    assert ev1.prev_event_hash == "0" * 64
    assert len(ev1.event_hash) == 64

    # 2. Append Audit Event 2 (Chained to Event 1)
    ev2 = await audit_repo.append(
        AuditEventCreateRequest(
            event_id="ev-02",
            engagement_id="eng-audit-01",
            correlation_id="corr-audit-01",
            event_type="task_dispatched",
            actor_type="AGENT",
            actor_id="agent-ciso-01",
            payload={"task_id": "T01"},
        )
    )
    assert ev2.seq == 2
    assert ev2.prev_event_hash == ev1.event_hash
    assert len(ev2.event_hash) == 64

    # 3. Append Audit Event 3 (Chained to Event 2)
    ev3 = await audit_repo.append(
        AuditEventCreateRequest(
            event_id="ev-03",
            engagement_id="eng-audit-01",
            correlation_id="corr-audit-01",
            event_type="approval_granted",
            actor_type="OPERATOR",
            actor_id="operator-01",
            payload={"gate_id": "gate-001"},
        )
    )
    assert ev3.seq == 3
    assert ev3.prev_event_hash == ev2.event_hash

    # 4. Verify Cryptographic Integrity
    valid, message = await audit_repo.verify_integrity("eng-audit-01")
    assert valid is True
    assert "verified cleanly" in message

    # 5. Immutability Enforcement: Calling update() or delete() MUST raise ImmutableAuditViolationError
    with pytest.raises(ImmutableAuditViolationError) as exc_info:
        await audit_repo.update("ev-01", payload={"tampered": True})
    assert "immutable and append-only" in str(exc_info.value)

    with pytest.raises(ImmutableAuditViolationError) as exc_info2:
        await audit_repo.delete("ev-01")
    assert "immutable and append-only" in str(exc_info2.value)

    await engine.dispose()
