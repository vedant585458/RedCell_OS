"""Concrete Workspace repository wrapping SQLAlchemy session."""

import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.workspace import (
    WorkspaceModel,
    WorkspaceResponse,
    WorkspaceStatus,
)
from app.repositories.base import BaseRepository


class WorkspaceRepository(BaseRepository[WorkspaceModel, str]):
    """Typed repository handling persistence and lookup for provisioned agent workspaces."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(WorkspaceModel, session)

    async def create(
        self,
        workspace_id: str,
        task_id: str,
        agent_id: str,
        engagement_id: str,
        workspace_path: str,
        tmp_path: str,
        artifacts_path: str,
        evidence_path: str,
        permissions_mode: str = "0700",
        metadata: dict | None = None,
    ) -> WorkspaceResponse:
        """Persist a new workspace record."""
        now = datetime.now(UTC).isoformat()
        model = WorkspaceModel(
            id=workspace_id,
            task_id=task_id,
            agent_id=agent_id,
            engagement_id=engagement_id,
            workspace_path=workspace_path,
            tmp_path=tmp_path,
            artifacts_path=artifacts_path,
            evidence_path=evidence_path,
            permissions_mode=permissions_mode,
            status=WorkspaceStatus.PROVISIONED.value,
            metadata_json=json.dumps(metadata or {}),
            created_at=now,
            updated_at=now,
        )
        self.session.add(model)
        await self.session.flush()
        return model.to_response()

    async def get_by_task_id(self, task_id: str) -> WorkspaceResponse | None:
        """Fetch workspace record by task ID."""
        stmt = select(WorkspaceModel).where(WorkspaceModel.task_id == task_id)
        res = await self.session.execute(stmt)
        model = res.scalar_one_or_none()
        return model.to_response() if model else None

    async def get_by_agent_id(self, agent_id: str) -> list[WorkspaceResponse]:
        """List all workspaces provisioned for an agent."""
        stmt = select(WorkspaceModel).where(WorkspaceModel.agent_id == agent_id)
        res = await self.session.execute(stmt)
        return [row.to_response() for row in res.scalars().all()]

    async def update_status(
        self, workspace_id: str, status: WorkspaceStatus | str
    ) -> WorkspaceResponse | None:
        """Update workspace lifecycle status."""
        status_val = status.value if isinstance(status, WorkspaceStatus) else status
        now = datetime.now(UTC).isoformat()

        model = await self.get_by_id(workspace_id)
        if not model:
            return None
        model.status = status_val
        model.updated_at = now
        await self.session.flush()
        return model.to_response()
