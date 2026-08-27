"""Unit and integration tests for ExecutionContext lifecycle, in-flight state tracking, pruning, and immutable audit archival."""

import asyncio

import pytest
from app.agents.execution_context import (
    MAX_MESSAGES_IN_ARCHIVE,
    MAX_SNIPPET_CHARS,
    ExecutionContextService,
    ExecutionContextStatus,
)
from app.domain.engagement import Base, EngagementCreateRequest
from app.domain.task import TaskCreateRequest, TaskStatus
from app.orchestrator import global_orchestrator
from app.repositories.unit_of_work import UnitOfWork
from app.services.org_bootstrap import OrgBootstrapService
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def setup_test_environment():
    """Setup test SQLite database, seed org, engagement, and a task."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    bootstrap = OrgBootstrapService(session_factory)
    await bootstrap.bootstrap_organization()

    async with UnitOfWork(session_factory) as uow:
        # Create engagement
        await uow.engagements.create_engagement(
            EngagementCreateRequest(
                engagement_id="eng-exec-ctx-test",
                title="Execution Context Test Engagement",
                organization="TargetFinance",
                authorized_by="CISO",
            )
        )
        # Create Task
        await uow.tasks.create_task(
            TaskCreateRequest(
                task_id="TASK_WEB_PROBE_01",
                engagement_id="eng-exec-ctx-test",
                department_id="dept_recon",
                title="Active Web Endpoint Probing",
                assigned_role="role_web_discovery",
                assigned_agent_id="agent-recon-01",
                priority=3,
            )
        )
        await uow.tasks.update_status("TASK_WEB_PROBE_01", TaskStatus.RUNNING)
        await uow.commit()

    return session_factory, engine


@pytest.mark.asyncio
async def test_execution_context_lifecycle_tracking_and_pruning():
    """Verify in-flight state tracking (commands, LLM turns, findings) and anti-bloat pruning."""
    session_factory, engine = await setup_test_environment()
    try:
        service = ExecutionContextService(session_factory)

        # 1. Initialize Context at task assignment
        ctx = service.create_context(
            task_id="TASK_WEB_PROBE_01",
            agent_id="agent-recon-01",
            role_id="role_web_discovery",
            engagement_id="eng-exec-ctx-test",
            department_id="dept_recon",
        )
        assert ctx.status == ExecutionContextStatus.INITIALIZED
        assert ctx.task_id == "TASK_WEB_PROBE_01"

        # 2. Record 60 LLM interaction turns (exceeding MAX_MESSAGES_IN_ARCHIVE)
        for i in range(30):
            ctx.record_llm_interaction(
                prompt_content=f"Analyze HTTP response header batch {i}",
                response_content=f"Identified Apache/2.4.52 framework signature in batch {i}",
            )
        assert len(ctx.llm_messages) == 60  # 30 user + 30 assistant messages
        assert ctx.status == ExecutionContextStatus.ACTIVE

        # 3. Record command execution with oversized output
        huge_stdout = "X" * 10000  # 10,000 characters
        cmd_rec = ctx.record_command(
            command=["httpx", "-u", "https://targetfinance.local", "-status-code"],
            exit_code=0,
            stdout=huge_stdout,
            stderr="",
            duration_sec=1.45,
        )
        # Verify snippet is capped to prevent bloat
        assert len(cmd_rec.stdout_snippet) == MAX_SNIPPET_CHARS

        # 4. Record security findings & approvals
        ctx.record_finding("FINDING-OPEN-REDIRECT-01")
        ctx.record_finding("FINDING-CORS-MISCONFIG-02")
        ctx.record_approval(
            gate_id="gate-scan-01",
            status="APPROVED",
            details={"operator": "sec-ops-lead"},
        )

        assert len(ctx.discovered_finding_ids) == 2
        assert len(ctx.approval_gate_records) == 1

        # 5. Prune for archival
        archive = ctx.prune_for_archival()
        assert len(archive.pruned_messages) == MAX_MESSAGES_IN_ARCHIVE
        assert archive.findings_count == 2
        assert archive.total_commands_executed == 1
        assert archive.total_llm_turns == 30
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_execution_context_archival_and_audit_retrieval():
    """Acceptance Criteria & Technical Decision: Completed task's context is archived to relational

    database and immutable audit store, retrievable for post-engagement forensics.
    """
    session_factory, engine = await setup_test_environment()
    try:
        service = ExecutionContextService(session_factory)

        # 1. Initialize and populate context
        ctx = service.create_context(
            task_id="TASK_WEB_PROBE_01",
            agent_id="agent-recon-01",
            role_id="role_web_discovery",
            engagement_id="eng-exec-ctx-test",
            department_id="dept_recon",
        )
        ctx.record_llm_interaction("Execute crawl", "Starting crawl on /api endpoints")
        ctx.record_command(
            command=["katana", "-u", "https://targetfinance.local"],
            exit_code=0,
            stdout="Discovered 14 endpoints",
            duration_sec=2.1,
        )
        ctx.record_finding("FINDING-INFO-DISCLOSURE-01")

        captured_events = []

        async def capture_event(event):
            captured_events.append(event)

        global_orchestrator.register_event_subscriber(capture_event)
        await global_orchestrator.start()

        # 2. Archive on task completion
        archive_res = await service.archive_context(
            task_id="TASK_WEB_PROBE_01",
            final_status=ExecutionContextStatus.COMPLETED,
        )

        assert archive_res.context_id == ctx.context_id
        assert archive_res.final_status == "COMPLETED"

        # 3. Active in-memory context should now be popped
        assert service.get_active_context("TASK_WEB_PROBE_01") is None

        # 4. Retrieve archived context from relational database
        retrieved = await service.get_archived_context_by_task("TASK_WEB_PROBE_01")
        assert retrieved is not None
        assert retrieved.context_id == ctx.context_id
        assert retrieved.task_id == "TASK_WEB_PROBE_01"
        assert retrieved.agent_id == "agent-recon-01"
        assert retrieved.total_commands_executed == 1
        assert retrieved.findings_count == 1
        assert "FINDING-INFO-DISCLOSURE-01" in retrieved.discovered_finding_ids

        # 5. Verify Immutable Audit Store contains archival event
        async with UnitOfWork(session_factory) as uow:
            audit_events = await uow.audit.list_by_engagement("eng-exec-ctx-test")
            ctx_audit = [
                e for e in audit_events if e.event_type == "execution_context_archived"
            ]
            assert len(ctx_audit) == 1
            assert ctx_audit[0].payload["context_id"] == ctx.context_id
            assert ctx_audit[0].payload["commands_count"] == 1

        await asyncio.sleep(0.05)

        # 6. Verify event was broadcast on orchestrator bus
        event_types = [e.event_type for e in captured_events]
        assert "execution_context_archived" in event_types
    finally:
        global_orchestrator.unregister_event_subscriber(capture_event)
        await global_orchestrator.stop()
        await engine.dispose()
