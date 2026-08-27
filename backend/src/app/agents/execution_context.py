"""Agent Execution Context lifecycle management, in-flight state tracking, pruning, and immutable archival."""

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.domain.audit import AuditEventCreateRequest
from app.domain.execution_context import (
    CommandExecutionRecord,
    ExecutionContextArchive,
    ExecutionContextStatus,
)
from app.llm.models import ChatMessage
from app.orchestrator.core import global_orchestrator
from app.repositories.unit_of_work import UnitOfWork

logger = get_logger("agents.execution_context")

MAX_SNIPPET_CHARS = 2000
MAX_MESSAGES_IN_ARCHIVE = 50


class ExecutionContext(BaseModel):
    """In-memory active working execution context tracking live agent state during a task."""

    context_id: str = Field(default_factory=lambda: f"ctx-{uuid.uuid4().hex[:8]}")
    task_id: str
    agent_id: str
    role_id: str
    engagement_id: str
    department_id: str
    status: ExecutionContextStatus = Field(default=ExecutionContextStatus.INITIALIZED)
    llm_messages: list[ChatMessage] = Field(default_factory=list)
    executed_commands: list[CommandExecutionRecord] = Field(default_factory=list)
    discovered_finding_ids: list[str] = Field(default_factory=list)
    approval_gate_records: list[dict[str, Any]] = Field(default_factory=list)
    scratchpad: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    closed_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def record_llm_interaction(self, prompt_content: str, response_content: str) -> None:
        """Append an LLM prompt/response exchange to the in-flight context."""
        self.llm_messages.append(ChatMessage(role="user", content=prompt_content))
        self.llm_messages.append(ChatMessage(role="assistant", content=response_content))
        self.status = ExecutionContextStatus.ACTIVE

    def record_command(
        self,
        command: list[str],
        exit_code: int,
        stdout: str = "",
        stderr: str = "",
        duration_sec: float = 0.0,
    ) -> CommandExecutionRecord:
        """Record a tool command execution, pruning output to prevent memory bloat."""
        rec = CommandExecutionRecord(
            command=command,
            exit_code=exit_code,
            stdout_snippet=stdout[:MAX_SNIPPET_CHARS] if stdout else "",
            stderr_snippet=stderr[:MAX_SNIPPET_CHARS] if stderr else "",
            duration_sec=duration_sec,
        )
        self.executed_commands.append(rec)
        self.status = ExecutionContextStatus.ACTIVE
        return rec

    def record_finding(self, finding_id: str) -> None:
        """Record a security finding discovered during this execution context."""
        if finding_id not in self.discovered_finding_ids:
            self.discovered_finding_ids.append(finding_id)
        self.status = ExecutionContextStatus.ACTIVE

    def record_approval(
        self, gate_id: str, status: str, details: dict[str, Any] | None = None
    ) -> None:
        """Record an approval gate evaluation."""
        self.approval_gate_records.append(
            {
                "gate_id": gate_id,
                "status": status,
                "timestamp": datetime.now(UTC).isoformat(),
                "details": details or {},
            }
        )

    def prune_for_archival(self) -> ExecutionContextArchive:
        """Anti-Bloat Strategy: Prune oversized command snippets and message logs before persistence."""
        pruned_messages = [
            {"role": m.role, "content": m.content[:MAX_SNIPPET_CHARS]}
            for m in self.llm_messages[-MAX_MESSAGES_IN_ARCHIVE:]
        ]
        pruned_commands = [cmd.model_dump() for cmd in self.executed_commands]

        return ExecutionContextArchive(
            context_id=self.context_id,
            task_id=self.task_id,
            agent_id=self.agent_id,
            role_id=self.role_id,
            engagement_id=self.engagement_id,
            department_id=self.department_id,
            final_status=self.status.value,
            total_commands_executed=len(self.executed_commands),
            total_llm_turns=len(self.llm_messages) // 2,
            findings_count=len(self.discovered_finding_ids),
            discovered_finding_ids=self.discovered_finding_ids,
            approval_gate_records=self.approval_gate_records,
            pruned_messages=pruned_messages,
            executed_commands=pruned_commands,
            scratchpad_summary=self.scratchpad,
            created_at=self.created_at,
            closed_at=self.closed_at or datetime.now(UTC).isoformat(),
            metadata=self.metadata,
        )


class ExecutionContextService:
    """Service managing the creation, in-flight mutation, and immutable archival of ExecutionContext instances."""

    def __init__(self, session_factory: Any) -> None:
        self.session_factory = session_factory
        self._active_contexts: dict[str, ExecutionContext] = {}  # task_id -> ExecutionContext

    def create_context(
        self,
        task_id: str,
        agent_id: str,
        role_id: str,
        engagement_id: str,
        department_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> ExecutionContext:
        """Initialize an active ExecutionContext at task assignment time."""
        ctx = ExecutionContext(
            task_id=task_id,
            agent_id=agent_id,
            role_id=role_id,
            engagement_id=engagement_id,
            department_id=department_id,
            status=ExecutionContextStatus.INITIALIZED,
            metadata=metadata or {},
        )
        self._active_contexts[task_id] = ctx
        logger.info(
            f"Initialized execution context '{ctx.context_id}' for agent '{agent_id}' on task '{task_id}'",
            context_id=ctx.context_id,
            task_id=task_id,
            agent_id=agent_id,
        )
        return ctx

    def get_active_context(self, task_id: str) -> ExecutionContext | None:
        """Fetch active in-flight context for a task."""
        return self._active_contexts.get(task_id)

    async def archive_context(
        self,
        task_id: str,
        final_status: ExecutionContextStatus | str = ExecutionContextStatus.COMPLETED,
        correlation_id: str = "",
    ) -> ExecutionContextArchive:
        """Prune and archive completed execution context into the relational database and immutable audit log.

        Technical Decision: Context is pruned and archived, satisfying full auditability requirements
        without suffering memory/storage bloat.
        """
        ctx = self._active_contexts.pop(task_id, None)
        if not ctx:
            # Check if already archived
            archived = await self.get_archived_context_by_task(task_id)
            if archived:
                return archived
            raise ValueError(f"No active or archived execution context found for task '{task_id}'.")

        status_val = (
            final_status
            if isinstance(final_status, ExecutionContextStatus)
            else ExecutionContextStatus(str(final_status))
        )
        ctx.status = status_val
        ctx.closed_at = datetime.now(UTC).isoformat()

        # 1. Prune context to prevent bloat
        archive = ctx.prune_for_archival()
        corr_id = correlation_id or f"corr-ctx-arch-{task_id}-{uuid.uuid4().hex[:8]}"

        # 2. Persist in database & immutable audit store
        async with UnitOfWork(self.session_factory) as uow:
            await uow.execution_contexts.save_archive(archive)

            # Record immutable audit event
            await uow.audit.append_audit_event(
                AuditEventCreateRequest(
                    event_id=f"aud-ctx-{archive.context_id[:8]}",
                    engagement_id=archive.engagement_id,
                    correlation_id=corr_id,
                    event_type="execution_context_archived",
                    actor_type="AGENT",
                    actor_id=archive.agent_id,
                    payload={
                        "context_id": archive.context_id,
                        "task_id": archive.task_id,
                        "agent_id": archive.agent_id,
                        "final_status": archive.final_status,
                        "commands_count": archive.total_commands_executed,
                        "findings_count": archive.findings_count,
                        "llm_turns": archive.total_llm_turns,
                    },
                )
            )
            await uow.commit()

        # 3. Broadcast archival event
        await global_orchestrator.emit_event(
            event_type="execution_context_archived",
            correlation_id=corr_id,
            engagement_id=archive.engagement_id,
            agent_id=archive.agent_id,
            task_id=archive.task_id,
            payload={
                "context_id": archive.context_id,
                "task_id": archive.task_id,
                "final_status": archive.final_status,
            },
        )

        logger.info(
            f"Archived execution context '{archive.context_id}' for task '{task_id}' (Status: {archive.final_status})",
            context_id=archive.context_id,
            task_id=task_id,
            status=archive.final_status,
        )

        return archive

    async def get_archived_context_by_task(self, task_id: str) -> ExecutionContextArchive | None:
        """Retrieve an archived execution context from the relational database."""
        async with UnitOfWork(self.session_factory) as uow:
            return await uow.execution_contexts.get_by_task_id(task_id)

    async def list_archived_contexts(self, engagement_id: str) -> list[ExecutionContextArchive]:
        """List all archived execution contexts for an engagement."""
        async with UnitOfWork(self.session_factory) as uow:
            return await uow.execution_contexts.list_by_engagement(engagement_id)
