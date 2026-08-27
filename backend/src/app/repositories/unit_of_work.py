"""Unit of Work pattern managing database transactions and repository aggregates."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import TracebackType
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repositories.agent_memory_repo import AgentMemoryRepository
from app.repositories.agent_repo import AgentRepository
from app.repositories.approval_repo import ApprovalRepository
from app.repositories.audit_repo import AuditRepository
from app.repositories.department_repo import DepartmentRepository
from app.repositories.engagement_repo import EngagementRepository
from app.repositories.execution_context_repo import ExecutionContextRepository
from app.repositories.execution_repo import ExecutionRepository
from app.repositories.finding_repo import FindingRepository
from app.repositories.message_repo import MessageRepository
from app.repositories.role_repo import RoleRepository
from app.repositories.task_repo import TaskRepository
from app.repositories.workspace_repo import WorkspaceRepository


class UnitOfWork:
    """Async Unit of Work coordinating transactional integrity across all repository aggregates."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory
        self.session: AsyncSession | None = None

        self.engagements: EngagementRepository
        self.departments: DepartmentRepository
        self.roles: RoleRepository
        self.agents: AgentRepository
        self.tasks: TaskRepository
        self.findings: FindingRepository
        self.approvals: ApprovalRepository
        self.audit: AuditRepository
        self.messages: MessageRepository
        self.executions: ExecutionRepository
        self.memories: AgentMemoryRepository
        self.execution_contexts: ExecutionContextRepository
        self.workspaces: WorkspaceRepository

    async def __aenter__(self) -> "UnitOfWork":
        self.session = self.session_factory()
        self.engagements = EngagementRepository(self.session)
        self.departments = DepartmentRepository(self.session)
        self.roles = RoleRepository(self.session)
        self.agents = AgentRepository(self.session)
        self.tasks = TaskRepository(self.session)
        self.findings = FindingRepository(self.session)
        self.approvals = ApprovalRepository(self.session)
        self.audit = AuditRepository(self.session)
        self.messages = MessageRepository(self.session)
        self.executions = ExecutionRepository(self.session)
        self.memories = AgentMemoryRepository(self.session)
        self.execution_contexts = ExecutionContextRepository(self.session)
        self.workspaces = WorkspaceRepository(self.session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self.session:
            if exc_type:
                await self.rollback()
            await self.session.close()
            self.session = None

    async def commit(self) -> None:
        """Commit the active transaction."""
        if self.session:
            await self.session.commit()

    async def rollback(self) -> None:
        """Rollback the active transaction."""
        if self.session:
            await self.session.rollback()


@asynccontextmanager
async def get_uow(session_factory: Any) -> AsyncIterator[UnitOfWork]:
    """Helper generator for dependency injection of UnitOfWork."""
    uow = UnitOfWork(session_factory)
    async with uow:
        yield uow
