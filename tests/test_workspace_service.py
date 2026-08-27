"""Unit and integration tests for WorkspaceService, directory isolation, permission bits, path-traversal protection, and cleanup."""

import asyncio
import os
import stat
import tempfile

import pytest
from app.domain.engagement import Base, EngagementCreateRequest
from app.domain.task import TaskCreateRequest, TaskStatus
from app.domain.workspace import WorkspaceStatus
from app.orchestrator import global_orchestrator
from app.repositories.unit_of_work import UnitOfWork
from app.services.org_bootstrap import OrgBootstrapService
from app.workspace.service import (
    PathTraversalError,
    WorkspaceService,
    sanitize_path_segment,
)
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def setup_test_environment(temp_dir: str):
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
                engagement_id="eng-ws-test",
                title="Workspace Provisioning Test",
                organization="CyberRange Corp",
                authorized_by="CISO",
            )
        )
        # Create Task
        await uow.tasks.create_task(
            TaskCreateRequest(
                task_id="TASK_PROV_01",
                engagement_id="eng-ws-test",
                department_id="dept_recon",
                title="Endpoint Discovery Task",
                assigned_role="role_web_discovery",
                assigned_agent_id="agent-recon-01",
            )
        )
        await uow.tasks.update_status("TASK_PROV_01", TaskStatus.RUNNING)
        await uow.commit()

    return session_factory, engine


@pytest.mark.asyncio
async def test_workspace_provisioning_structure_and_permissions():
    """Acceptance Criteria & Technical Decision: Assigning a task provisions an isolated workspace

    following the /data/workspaces/{engagement_id}/{agent_id}/{task_id}/ convention with restrictive 0700 permissions.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        session_factory, engine = await setup_test_environment(temp_dir)
        try:
            captured_events = []

            async def capture_event(event):
                captured_events.append(event)

            global_orchestrator.register_event_subscriber(capture_event)
            await global_orchestrator.start()

            service = WorkspaceService(
                session_factory=session_factory,
                base_dir=temp_dir,
                permissions_mode=0o700,
            )

            # Provision workspace
            ws_resp = await service.provision_workspace(
                task_id="TASK_PROV_01",
                agent_id="agent-recon-01",
                engagement_id="eng-ws-test",
            )

            assert ws_resp.task_id == "TASK_PROV_01"
            assert ws_resp.agent_id == "agent-recon-01"
            assert ws_resp.status == WorkspaceStatus.PROVISIONED

            # 1. Verify directory structure on disk
            root_dir = ws_resp.workspace_path
            tmp_dir = ws_resp.tmp_path
            artifacts_dir = ws_resp.artifacts_path
            evidence_dir = ws_resp.evidence_path

            assert os.path.exists(root_dir) and os.path.isdir(root_dir)
            assert os.path.exists(tmp_dir) and os.path.isdir(tmp_dir)
            assert os.path.exists(artifacts_dir) and os.path.isdir(artifacts_dir)
            assert os.path.exists(evidence_dir) and os.path.isdir(evidence_dir)

            # Verify subfolder naming matches defined spec
            assert os.path.basename(tmp_dir) == "tmp"
            assert os.path.basename(artifacts_dir) == "artifacts"
            assert os.path.basename(evidence_dir) == "evidence"

            # 2. Verify Restrictive Permission bits (0o700 = rwx------)
            root_stat = os.stat(root_dir)
            mode_bits = stat.S_IMODE(root_stat.st_mode)
            assert mode_bits == 0o700

            # 3. Verify Database Entity persistence
            async with UnitOfWork(session_factory) as uow:
                db_ws = await uow.workspaces.get_by_task_id("TASK_PROV_01")
                assert db_ws is not None
                assert db_ws.workspace_path == root_dir
                assert db_ws.status == WorkspaceStatus.PROVISIONED

                # Verify audit event
                audit_events = await uow.audit.list_by_engagement("eng-ws-test")
                ws_audit = [
                    e for e in audit_events if e.event_type == "workspace_provisioned"
                ]
                assert len(ws_audit) == 1
                assert ws_audit[0].payload["task_id"] == "TASK_PROV_01"

            await asyncio.sleep(0.05)

            # 4. Verify WorkspaceInitialized event emitted
            event_types = [e.event_type for e in captured_events]
            assert "workspace_initialized" in event_types
        finally:
            global_orchestrator.unregister_event_subscriber(capture_event)
            await global_orchestrator.stop()
            await engine.dispose()


def test_path_traversal_sanitization_protection():
    """Risk Mitigation Test: Path traversal sequences and illegal characters in IDs are strictly blocked."""
    # Valid segments
    assert sanitize_path_segment("eng-101") == "eng-101"
    assert sanitize_path_segment("agent_recon_01") == "agent_recon_01"
    assert sanitize_path_segment("task-probe.01") == "task-probe.01"

    # Directory traversal attempts -> PathTraversalError
    with pytest.raises(PathTraversalError):
        sanitize_path_segment("../../etc/passwd")

    with pytest.raises(PathTraversalError):
        sanitize_path_segment("..")

    with pytest.raises(PathTraversalError):
        sanitize_path_segment("agent/sub/path")

    with pytest.raises(PathTraversalError):
        sanitize_path_segment("task\x00nullbyte")

    with pytest.raises(PathTraversalError):
        sanitize_path_segment("task;rm -rf /")


@pytest.mark.asyncio
async def test_workspace_cleanup_retains_evidence():
    """Verify workspace cleanup purges ephemeral tmp scratchpad while preserving evidence artifacts."""
    with tempfile.TemporaryDirectory() as temp_dir:
        session_factory, engine = await setup_test_environment(temp_dir)
        try:
            service = WorkspaceService(
                session_factory=session_factory, base_dir=temp_dir
            )
            ws_resp = await service.provision_workspace(
                task_id="TASK_PROV_01",
                agent_id="agent-recon-01",
                engagement_id="eng-ws-test",
            )

            # Populate scratchpad, artifacts, and evidence files
            tmp_file = os.path.join(ws_resp.tmp_path, "scratch.txt")
            artifact_file = os.path.join(ws_resp.artifacts_path, "nmap_output.xml")
            evidence_file = os.path.join(ws_resp.evidence_path, "sqli_response.http")

            def write_file(p: str, content: str) -> None:
                with open(p, "w") as f:
                    f.write(content)

            write_file(tmp_file, "temporary buffer")
            write_file(artifact_file, "<xml>scan</xml>")
            write_file(evidence_file, "HTTP/1.1 200 OK")

            assert os.path.exists(tmp_file)
            assert os.path.exists(artifact_file)
            assert os.path.exists(evidence_file)

            # Cleanup with purge_all=False (standard task completion cleanup)
            await service.cleanup_workspace("TASK_PROV_01", purge_all=False)

            # tmp scratch file must be deleted
            assert not os.path.exists(tmp_file)
            # Artifacts and evidence must remain preserved!
            assert os.path.exists(artifact_file)
            assert os.path.exists(evidence_file)

            # Cleanup with purge_all=True (purge entire workspace)
            await service.cleanup_workspace("TASK_PROV_01", purge_all=True)
            assert not os.path.exists(ws_resp.workspace_path)
        finally:
            await engine.dispose()
