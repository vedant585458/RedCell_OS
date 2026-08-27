"""Workspace Provisioning Service creating isolated, permission-restricted directories for agent task execution."""

import os
import re
import shutil
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.logging import get_logger
from app.domain.audit import AuditEventCreateRequest
from app.domain.workspace import WorkspaceResponse, WorkspaceStatus
from app.orchestrator.core import global_orchestrator
from app.repositories.unit_of_work import UnitOfWork

logger = get_logger("workspace.service")

# Regex allowing only safe alphanumeric slugs, dashes, underscores, and dots
SAFE_PATH_COMPONENT_REGEX = re.compile(r"^[a-zA-Z0-9_\-\.]+$")


class PathTraversalError(ValueError):
    """Raised when an identifier contains directory traversal sequences or illegal characters."""

    def __init__(self, segment: str) -> None:
        self.segment = segment
        super().__init__(
            f"Security Exception: Path traversal attempt detected in segment '{segment}'."
        )


class WorkspaceInitializedEventPayload(BaseModel):
    """Structured payload emitted when an agent workspace is provisioned on disk."""

    workspace_id: str
    task_id: str
    agent_id: str
    engagement_id: str
    workspace_path: str
    tmp_path: str
    artifacts_path: str
    evidence_path: str
    permissions_mode: str
    correlation_id: str
    timestamp_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


def sanitize_path_segment(segment: str) -> str:
    """Validate and sanitize a path component, blocking directory traversal attacks (e.g. '..', '/', null bytes)."""
    if not segment or not isinstance(segment, str):
        raise PathTraversalError("empty_segment")

    cleaned = segment.strip()
    if ".." in cleaned or "/" in cleaned or "\\" in cleaned or "\x00" in cleaned:
        raise PathTraversalError(segment)

    if not SAFE_PATH_COMPONENT_REGEX.match(cleaned):
        raise PathTraversalError(segment)

    return cleaned


class WorkspaceService:
    """Service managing the lifecycle, isolated directory creation, permissions, and cleanup of agent workspaces."""

    def __init__(
        self,
        session_factory: Any,
        base_dir: str | None = None,
        permissions_mode: int = 0o700,
    ) -> None:
        self.session_factory = session_factory
        self.base_dir = os.path.abspath(base_dir or os.path.join(settings.data_dir, "workspaces"))
        self.permissions_mode = permissions_mode

    def get_workspace_root(self, engagement_id: str, agent_id: str, task_id: str) -> str:
        """Technical Decision: Workspace path convention /data/workspaces/{engagement_id}/{agent_id}/{task_id}/."""
        safe_eng = sanitize_path_segment(engagement_id)
        safe_agent = sanitize_path_segment(agent_id)
        safe_task = sanitize_path_segment(task_id)

        target_path = os.path.abspath(os.path.join(self.base_dir, safe_eng, safe_agent, safe_task))

        # Hard boundary validation: Ensure resolved path is strictly within base_dir
        if not target_path.startswith(self.base_dir):
            raise PathTraversalError(f"{engagement_id}/{agent_id}/{task_id}")

        return target_path

    async def provision_workspace(
        self,
        task_id: str,
        agent_id: str,
        engagement_id: str,
        metadata: dict[str, Any] | None = None,
        correlation_id: str = "",
    ) -> WorkspaceResponse:
        """Provision an isolated filesystem workspace with tmp, artifacts, and evidence subfolders and restrictive permissions."""
        corr_id = correlation_id or f"corr-ws-{task_id}-{uuid.uuid4().hex[:8]}"
        workspace_id = f"ws-{uuid.uuid4().hex[:8]}"

        # 1. Path computation and directory structure
        root_path = self.get_workspace_root(engagement_id, agent_id, task_id)
        tmp_path = os.path.join(root_path, "tmp")
        artifacts_path = os.path.join(root_path, "artifacts")
        evidence_path = os.path.join(root_path, "evidence")

        # 2. Create directories with restrictive permission bits (0o700)
        for directory in [root_path, tmp_path, artifacts_path, evidence_path]:
            os.makedirs(directory, exist_ok=True)
            try:
                os.chmod(directory, self.permissions_mode)
            except OSError as err:
                logger.warning(
                    f"Could not set permissions {oct(self.permissions_mode)} on {directory}: {err}"
                )

        # 3. Persist Workspace entity in relational database
        async with UnitOfWork(self.session_factory) as uow:
            workspace_resp = await uow.workspaces.create(
                workspace_id=workspace_id,
                task_id=task_id,
                agent_id=agent_id,
                engagement_id=engagement_id,
                workspace_path=root_path,
                tmp_path=tmp_path,
                artifacts_path=artifacts_path,
                evidence_path=evidence_path,
                permissions_mode=oct(self.permissions_mode),
                metadata=metadata or {},
            )

            # Record immutable audit event
            await uow.audit.append_audit_event(
                AuditEventCreateRequest(
                    event_id=f"aud-ws-{workspace_id[:8]}",
                    engagement_id=engagement_id,
                    correlation_id=corr_id,
                    event_type="workspace_provisioned",
                    actor_type="SYSTEM",
                    actor_id="workspace_service",
                    payload={
                        "workspace_id": workspace_id,
                        "task_id": task_id,
                        "agent_id": agent_id,
                        "workspace_path": root_path,
                        "permissions": oct(self.permissions_mode),
                    },
                )
            )
            await uow.commit()

        # 4. Broadcast WorkspaceInitialized event over orchestrator bus
        event_payload = WorkspaceInitializedEventPayload(
            workspace_id=workspace_id,
            task_id=task_id,
            agent_id=agent_id,
            engagement_id=engagement_id,
            workspace_path=root_path,
            tmp_path=tmp_path,
            artifacts_path=artifacts_path,
            evidence_path=evidence_path,
            permissions_mode=oct(self.permissions_mode),
            correlation_id=corr_id,
        )

        await global_orchestrator.emit_event(
            event_type="workspace_initialized",
            correlation_id=corr_id,
            engagement_id=engagement_id,
            agent_id=agent_id,
            task_id=task_id,
            payload=event_payload.model_dump(),
        )

        logger.info(
            f"Provisioned isolated workspace for agent '{agent_id}' on task '{task_id}' at '{root_path}'",
            workspace_id=workspace_id,
            path=root_path,
        )

        return workspace_resp

    async def get_workspace_by_task(self, task_id: str) -> WorkspaceResponse | None:
        """Fetch workspace metadata for a task."""
        async with UnitOfWork(self.session_factory) as uow:
            return await uow.workspaces.get_by_task_id(task_id)

    async def cleanup_workspace(
        self,
        task_id: str,
        purge_all: bool = False,
    ) -> bool:
        """Clean up ephemeral files (tmp scratchpad) after task completion, preserving evidence and artifacts unless purge_all=True."""
        async with UnitOfWork(self.session_factory) as uow:
            ws = await uow.workspaces.get_by_task_id(task_id)
            if not ws:
                return False

            if purge_all:
                if os.path.exists(ws.workspace_path):
                    shutil.rmtree(ws.workspace_path, ignore_errors=True)
                await uow.workspaces.update_status(ws.id, WorkspaceStatus.CLEANED_UP)
            else:
                # Purge only tmp/ directory
                if os.path.exists(ws.tmp_path):
                    shutil.rmtree(ws.tmp_path, ignore_errors=True)
                    os.makedirs(ws.tmp_path, exist_ok=True)
                    os.chmod(ws.tmp_path, self.permissions_mode)
                await uow.workspaces.update_status(ws.id, WorkspaceStatus.ARCHIVED)

            await uow.commit()
            return True


# Global singleton instance of WorkspaceService
global_workspace_service = WorkspaceService(None)
