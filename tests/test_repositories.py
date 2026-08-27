"""Unit tests for the generic BaseRepository, concrete domain repositories, and UnitOfWork."""

import pytest
from app.domain.agent import AgentCreateRequest, AgentStatus
from app.domain.approval import ApprovalRequestSchema, ApprovalStatus
from app.domain.audit import AuditEventCreateRequest, ImmutableAuditViolationError
from app.domain.communication import MessageCreateRequest, MessageType
from app.domain.department import DepartmentCreateRequest
from app.domain.engagement import Base, EngagementCreateRequest
from app.domain.execution import CommandRecordSchema, ExecutionCreateRequest
from app.domain.finding import (
    EvidenceCreateRequest,
    EvidenceType,
    FindingCreateRequest,
    FindingSeverity,
    RiskScoreCreateRequest,
)
from app.domain.role import RoleCreateRequest
from app.domain.task import TaskCreateRequest
from app.repositories.unit_of_work import UnitOfWork
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def setup_test_session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False), engine


@pytest.mark.asyncio
async def test_unit_of_work_multi_aggregate_transaction():
    session_factory, engine = await setup_test_session_factory()
    try:
        async with UnitOfWork(session_factory) as uow:
            # 1. Department & Role
            await uow.departments.upsert_department(
                DepartmentCreateRequest(id="dept_recon", name="Reconnaissance")
            )
            await uow.roles.upsert_role(
                RoleCreateRequest(
                    id="role_recon",
                    name="Recon Lead",
                    department_id="dept_recon",
                    system_prompt_template="tpl",
                )
            )

            # 2. Engagement
            eng = await uow.engagements.create_engagement(
                EngagementCreateRequest(
                    engagement_id="eng-uow-01",
                    title="Unit of Work Test Engagement",
                    organization="Acme Security",
                    authorized_by="Lead CISO",
                )
            )
            assert eng.engagement_id == "eng-uow-01"

            # 3. Agent
            agent = await uow.agents.create_agent(
                AgentCreateRequest(
                    id="agent-recon-01",
                    role_id="role_recon",
                    department_id="dept_recon",
                    display_name="Recon Agent Alpha",
                    status=AgentStatus.IDLE,
                )
            )
            assert agent.id == "agent-recon-01"

            # 4. Task
            task = await uow.tasks.create_task(
                TaskCreateRequest(
                    task_id="TASK-01",
                    engagement_id="eng-uow-01",
                    department_id="dept_recon",
                    title="Port Scan Attack Surface",
                    assigned_role="role_recon",
                    assigned_agent_id="agent-recon-01",
                )
            )
            assert task.task_id == "TASK-01"

            # 5. Finding with Evidence & RiskScore
            finding = await uow.findings.create_finding(
                FindingCreateRequest(
                    finding_id="FINDING-001",
                    engagement_id="eng-uow-01",
                    task_id="TASK-01",
                    agent_id="agent-recon-01",
                    title="Unauthenticated Debug Config Leak",
                    description="Leaking secrets on port 8088",
                    severity=FindingSeverity.HIGH,
                    target_endpoint="http://127.0.0.1:8088/api/v1/debug/config",
                    evidence=[
                        EvidenceCreateRequest(
                            id="ev-01",
                            evidence_type=EvidenceType.RAW_OUTPUT,
                            artifact_path="/data/evidence/dump.json",
                            sha256_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                        )
                    ],
                    risk_score=RiskScoreCreateRequest(cvss_v31_base_score=7.5),
                )
            )
            assert finding.finding_id == "FINDING-001"
            assert len(finding.evidence) == 1

            # 6. Approval Gate
            appr = await uow.approvals.create_request(
                ApprovalRequestSchema(
                    id="gate-01",
                    engagement_id="eng-uow-01",
                    task_id="TASK-01",
                    agent_id="agent-recon-01",
                    category="ACTIVE_EXPLOITATION_PROBE",
                    target_uri="http://127.0.0.1:8088/api/v1/debug/config",
                    risk_description="Probe unauthenticated config",
                )
            )
            assert appr.status == ApprovalStatus.PENDING

            # 7. Agent Message & Execution Record
            msg = await uow.messages.send_message(
                MessageCreateRequest(
                    id="msg-01",
                    engagement_id="eng-uow-01",
                    sender_agent_id="agent-recon-01",
                    content="Task completed",
                    message_type=MessageType.STATUS_UPDATE,
                )
            )
            assert msg.id == "msg-01"

            exec_rec = await uow.executions.record_execution(
                ExecutionCreateRequest(
                    id="exec-01",
                    engagement_id="eng-uow-01",
                    task_id="TASK-01",
                    agent_id="agent-recon-01",
                    workspace_path="/data/workspaces/agent-recon-01",
                    pid=2048,
                    exit_code=0,
                    duration_sec=0.85,
                    command=CommandRecordSchema(
                        raw_command="nmap -sV 127.0.0.1",
                        sanitized_command="nmap -sV 127.0.0.1",
                        target="127.0.0.1",
                        tool_name="nmap",
                    ),
                )
            )
            assert exec_rec.id == "exec-01"

            # 8. Cryptographic Audit Log
            audit_rec = await uow.audit.append_audit_event(
                AuditEventCreateRequest(
                    event_id="aud-01",
                    engagement_id="eng-uow-01",
                    correlation_id="corr-uow-01",
                    event_type="task_executed",
                    actor_id="agent-recon-01",
                    payload={"task_id": "TASK-01"},
                )
            )
            assert audit_rec.seq == 1

            # Commit everything atomically
            await uow.commit()

        # Verify persistence in a new UnitOfWork session
        async with UnitOfWork(session_factory) as uow2:
            assert await uow2.engagements.exists("eng-uow-01") is True
            assert await uow2.agents.count() == 1
            assert await uow2.tasks.count() == 1
            assert await uow2.findings.count() == 1
            assert await uow2.approvals.count() == 1
            assert await uow2.messages.count() == 1
            assert await uow2.executions.count() == 1
            assert await uow2.audit.count() == 1

            # Verify cryptographic audit chain integrity
            valid, msg_str = await uow2.audit.verify_integrity("eng-uow-01")
            assert valid is True
            assert "verified cleanly" in msg_str
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_unit_of_work_rollback_on_exception():
    session_factory, engine = await setup_test_session_factory()
    try:
        try:
            async with UnitOfWork(session_factory) as uow:
                await uow.departments.upsert_department(
                    DepartmentCreateRequest(id="dept_doomed", name="Doomed Dept")
                )
                # Raise unhandled error before commit
                raise RuntimeError("Intentional error triggering rollback")
        except RuntimeError:
            pass

        # Verify department was NOT persisted
        async with UnitOfWork(session_factory) as uow2:
            assert await uow2.departments.exists("dept_doomed") is False
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_audit_repository_immutability_enforcement():
    session_factory, engine = await setup_test_session_factory()
    try:
        async with UnitOfWork(session_factory) as uow:
            await uow.engagements.create_engagement(
                EngagementCreateRequest(
                    engagement_id="eng-immut-01",
                    title="Title",
                    organization="Org",
                    authorized_by="CISO",
                )
            )
            await uow.audit.append_audit_event(
                AuditEventCreateRequest(
                    event_id="aud-immut-01",
                    engagement_id="eng-immut-01",
                    correlation_id="corr-01",
                    event_type="test_event",
                    actor_id="agent-01",
                )
            )
            await uow.commit()

            # Update attempt must raise ImmutableAuditViolationError
            with pytest.raises(ImmutableAuditViolationError) as exc_info:
                await uow.audit.update("aud-immut-01", payload={"tampered": True})
            assert "immutable" in str(exc_info.value)

            # Delete attempt must raise ImmutableAuditViolationError
            with pytest.raises(ImmutableAuditViolationError) as exc_info2:
                await uow.audit.delete("aud-immut-01")
            assert "immutable" in str(exc_info2.value)
    finally:
        await engine.dispose()
