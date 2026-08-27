"""Unit and integration tests for WorkspaceCleanupService, selective tmp deletion, retention windows, and evidence immutability negative testing."""

import os
import tempfile
import time

import pytest
from app.domain.engagement import Base, EngagementCreateRequest
from app.domain.task import TaskCreateRequest, TaskStatus
from app.domain.workspace import WorkspaceStatus
from app.repositories.unit_of_work import UnitOfWork
from app.services.org_bootstrap import OrgBootstrapService
from app.workspace.cleanup import (
    WorkspaceCleanupService,
    WorkspaceRetentionPolicy,
)
from app.workspace.service import WorkspaceService
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def setup_test_environment(temp_dir: str):
    """Setup test SQLite database, seed org, engagement, and tasks."""
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
                engagement_id="eng-clean-test",
                title="Workspace Cleanup Test Engagement",
                organization="SecureDefense Inc",
                authorized_by="CISO",
            )
        )
        # Create Task
        await uow.tasks.create_task(
            TaskCreateRequest(
                task_id="TASK_CLEAN_01",
                engagement_id="eng-clean-test",
                department_id="dept_recon",
                title="Port Scanning & OSINT",
                assigned_role="role_web_discovery",
                assigned_agent_id="agent-recon-01",
            )
        )
        await uow.tasks.update_status("TASK_CLEAN_01", TaskStatus.COMPLETED)
        await uow.commit()

    return session_factory, engine


def write_test_file(path: str, content: str) -> None:
    """Helper writing plain text to a file path."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def read_test_file(path: str) -> str:
    """Helper reading plain text from a file path."""
    with open(path) as f:
        return f.read()


@pytest.mark.asyncio
async def test_selective_cleanup_deletes_tmp_and_preserves_evidence():
    """Acceptance Criteria & Technical Decision: Cleanup deletes tmp files while strictly leaving

    evidence artifacts and scan artifacts intact.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        session_factory, engine = await setup_test_environment(temp_dir)
        try:
            ws_service = WorkspaceService(
                session_factory=session_factory, base_dir=temp_dir
            )
            cleanup_service = WorkspaceCleanupService(session_factory=session_factory)

            # 1. Provision workspace
            ws_resp = await ws_service.provision_workspace(
                task_id="TASK_CLEAN_01",
                agent_id="agent-recon-01",
                engagement_id="eng-clean-test",
            )

            # 2. Populate tmp/ with 4 temporary scratchpad files
            for i in range(1, 5):
                write_test_file(
                    os.path.join(ws_resp.tmp_path, f"scratch_pipe_{i}.buf"),
                    f"temporary buffer content {i}" * 50,
                )

            # 3. Populate evidence/ with 3 critical proof-of-concept evidence files
            evidence_files = [
                os.path.join(ws_resp.evidence_path, "sqli_response.http"),
                os.path.join(ws_resp.evidence_path, "privesc_proof.txt"),
                os.path.join(ws_resp.evidence_path, "poc_payload.bin"),
            ]
            for ev_file in evidence_files:
                write_test_file(ev_file, "CRITICAL VERIFIED EXPLOIT EVIDENCE")

            # 4. Populate artifacts/ with 2 scan output logs
            artifact_files = [
                os.path.join(ws_resp.artifacts_path, "nmap_output.xml"),
                os.path.join(ws_resp.artifacts_path, "httpx_routes.json"),
            ]
            for art_file in artifact_files:
                write_test_file(art_file, '{"endpoints": ["/api/v1"]}')

            # 5. Run Selective Cleanup
            report = await cleanup_service.clean_task_workspace(
                task_id="TASK_CLEAN_01",
                force_immediate_tmp=True,
            )

            # Assertions on Cleanup Report
            assert report.deleted_tmp_files_count == 4
            assert report.freed_bytes > 0
            assert report.preserved_evidence_files_count == 3
            assert report.preserved_artifacts_files_count == 2
            assert report.evidence_preserved is True
            assert report.status == WorkspaceStatus.ARCHIVED.value

            # 6. Verify filesystem reality: tmp files are gone
            for i in range(1, 5):
                assert not os.path.exists(
                    os.path.join(ws_resp.tmp_path, f"scratch_pipe_{i}.buf")
                )

            # 7. Verify filesystem reality: ALL evidence files remain 100% intact!
            for ev_file in evidence_files:
                assert os.path.exists(ev_file)
                assert read_test_file(ev_file) == "CRITICAL VERIFIED EXPLOIT EVIDENCE"

            # 8. Verify artifacts remain intact
            for art_file in artifact_files:
                assert os.path.exists(art_file)

            # 9. Verify Database & Immutable Audit Store
            async with UnitOfWork(session_factory) as uow:
                db_ws = await uow.workspaces.get_by_task_id("TASK_CLEAN_01")
                assert db_ws is not None
                assert db_ws.status == WorkspaceStatus.ARCHIVED

                audit_events = await uow.audit.list_by_engagement("eng-clean-test")
                clean_audits = [
                    e for e in audit_events if e.event_type == "workspace_tmp_cleaned"
                ]
                assert len(clean_audits) == 1
                assert clean_audits[0].payload["preserved_evidence_files_count"] == 3
        finally:
            await engine.dispose()


@pytest.mark.asyncio
async def test_accidental_evidence_deletion_negative_security_test():
    """Negative Security Test: Explicitly assert that evidence paths are never modified or purged."""
    with tempfile.TemporaryDirectory() as temp_dir:
        session_factory, engine = await setup_test_environment(temp_dir)
        try:
            ws_service = WorkspaceService(
                session_factory=session_factory, base_dir=temp_dir
            )
            cleanup_service = WorkspaceCleanupService(session_factory=session_factory)

            ws_resp = await ws_service.provision_workspace(
                task_id="TASK_CLEAN_01",
                agent_id="agent-recon-01",
                engagement_id="eng-clean-test",
            )

            # Create evidence file
            evidence_file = os.path.join(ws_resp.evidence_path, "important_proof.raw")
            write_test_file(evidence_file, "Immutable Evidence Record")

            # Run cleanup multiple times consecutively
            for _ in range(3):
                report = await cleanup_service.clean_task_workspace("TASK_CLEAN_01")
                assert report.evidence_preserved is True
                assert os.path.exists(evidence_file)

            # Content must never be altered or corrupted
            assert read_test_file(evidence_file) == "Immutable Evidence Record"
        finally:
            await engine.dispose()


@pytest.mark.asyncio
async def test_configurable_retention_window():
    """Verify configurable retention window deletes only files exceeding the configured threshold."""
    with tempfile.TemporaryDirectory() as temp_dir:
        session_factory, engine = await setup_test_environment(temp_dir)
        try:
            # Policy: 300 seconds retention (5 minutes)
            policy = WorkspaceRetentionPolicy(tmp_retention_seconds=300.0)
            ws_service = WorkspaceService(
                session_factory=session_factory, base_dir=temp_dir
            )
            cleanup_service = WorkspaceCleanupService(
                session_factory=session_factory, policy=policy
            )

            ws_resp = await ws_service.provision_workspace(
                task_id="TASK_CLEAN_01",
                agent_id="agent-recon-01",
                engagement_id="eng-clean-test",
            )

            # 1. Create fresh tmp file (mtime = now)
            fresh_tmp_file = os.path.join(ws_resp.tmp_path, "fresh_scratch.tmp")
            write_test_file(fresh_tmp_file, "freshly written buffer")

            # 2. Create aged tmp file (mtime = now - 600 seconds)
            aged_tmp_file = os.path.join(ws_resp.tmp_path, "aged_scratch.tmp")
            write_test_file(aged_tmp_file, "old buffer from 10 mins ago")
            past_time = time.time() - 600.0
            os.utime(aged_tmp_file, (past_time, past_time))

            # Run cleanup with force_immediate_tmp=False (respects retention threshold)
            report = await cleanup_service.clean_task_workspace(
                task_id="TASK_CLEAN_01",
                force_immediate_tmp=False,
            )

            # Only the aged file should be deleted (1 file)
            assert report.deleted_tmp_files_count == 1
            assert not os.path.exists(aged_tmp_file)
            # The fresh file (<300s) must be preserved!
            assert os.path.exists(fresh_tmp_file)
        finally:
            await engine.dispose()


@pytest.mark.asyncio
async def test_batch_retention_cleanup_across_engagement():
    """Verify batch cleanup processes multiple workspaces across an engagement."""
    with tempfile.TemporaryDirectory() as temp_dir:
        session_factory, engine = await setup_test_environment(temp_dir)
        try:
            ws_service = WorkspaceService(
                session_factory=session_factory, base_dir=temp_dir
            )
            cleanup_service = WorkspaceCleanupService(session_factory=session_factory)

            # Create 2 additional tasks and workspaces (TASK_CLEAN_02, TASK_CLEAN_03)
            async with UnitOfWork(session_factory) as uow:
                for i in (2, 3):
                    await uow.tasks.create_task(
                        TaskCreateRequest(
                            task_id=f"TASK_CLEAN_0{i}",
                            engagement_id="eng-clean-test",
                            department_id="dept_recon",
                            title=f"Recon Phase {i}",
                            assigned_role="role_web_discovery",
                            assigned_agent_id="agent-recon-01",
                        )
                    )
                await uow.commit()

            # Provision workspaces for all 3 tasks (01, 02, 03)
            for i in (1, 2, 3):
                ws = await ws_service.provision_workspace(
                    task_id=f"TASK_CLEAN_0{i}",
                    agent_id="agent-recon-01",
                    engagement_id="eng-clean-test",
                )
                # Put a tmp file and an evidence file in each
                write_test_file(os.path.join(ws.tmp_path, "pipe.tmp"), "scratch")
                write_test_file(os.path.join(ws.evidence_path, "proof.txt"), "evidence")

            # Run batch retention cleanup
            batch_report = await cleanup_service.run_batch_retention_cleanup(
                engagement_id="eng-clean-test",
                force_immediate_tmp=True,
            )

            assert batch_report.total_workspaces_processed == 3
            assert batch_report.total_tmp_files_deleted == 3
            assert batch_report.total_evidence_files_preserved == 3
        finally:
            await engine.dispose()
