"""Agent Long-Term Memory Service with automated anti-poisoning heuristic filter and CISO review."""

import re
import uuid
from typing import Any

from app.core.logging import get_logger
from app.domain.agent_memory import (
    AgentMemoryCreateRequest,
    AgentMemoryResponse,
    MemoryStatus,
    MemoryType,
)
from app.domain.audit import AuditEventCreateRequest
from app.orchestrator.core import global_orchestrator
from app.repositories.unit_of_work import UnitOfWork

logger = get_logger("agents.memory_service")


class MemoryPoisoningFilter:
    """Automated heuristic filter screening proposed agent memories for poisoning, scope violations, and bad inferences."""

    # Patterns attempting to bypass ROE or forge scope permissions
    FORBIDDEN_SCOPE_OVERRIDE_PATTERNS = [
        re.compile(
            r"\b(?:out\s*of\s*scope\s*is\s*allowed|ignore\s*roe|bypass\s*permission)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:disable\s*kill\s*switch|execute\s*destructive|wipe\s*disk)\b", re.IGNORECASE
        ),
        re.compile(
            r"\b(?:unrestricted\s*target|ignore\s*allowlist|ignore\s*exclusion)\b", re.IGNORECASE
        ),
    ]

    def evaluate(self, req: AgentMemoryCreateRequest) -> tuple[bool, str]:
        """Screen proposed memory entry. Returns (is_safe, rationale)."""
        content_lower = req.content.strip().lower()

        # 1. Content length sanity
        if len(content_lower) < 8:
            return False, "Proposed memory content is too brief or trivial (< 8 characters)."

        # 2. Anti-Scope-Bypass and Poisoning Check
        for pattern in self.FORBIDDEN_SCOPE_OVERRIDE_PATTERNS:
            if pattern.search(content_lower):
                logger.warning(
                    f"Memory poisoning attempt rejected: matches forbidden pattern '{pattern.pattern}'",
                    role_id=req.role_id,
                    key=req.key,
                )
                return (
                    False,
                    "Flagged by anti-poisoning filter: contains forbidden scope/ROE bypass directive.",
                )

        # 3. Confidence sanity check
        if req.confidence_score < 0.1 or req.confidence_score > 1.0:
            return False, "Confidence score must be bounded between 0.1 and 1.0."

        return True, "Passed automated safety heuristics."


class AgentMemoryService:
    """Service managing per-role persistent long-term memory propositions, heuristic safety filtering, and query retrieval."""

    def __init__(
        self,
        session_factory: Any,
        poisoning_filter: MemoryPoisoningFilter | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.poisoning_filter = poisoning_filter or MemoryPoisoningFilter()

    async def propose_memory(
        self,
        req: AgentMemoryCreateRequest,
        auto_review: bool = True,
        correlation_id: str = "",
    ) -> AgentMemoryResponse:
        """Submit a new memory observation for a specialist role.

        Technical Decision: Screened by automated heuristic filter to prevent memory poisoning
        from bad inferences before approval.
        """
        corr_id = correlation_id or f"corr-mem-{req.key}-{uuid.uuid4().hex[:8]}"

        # 1. Screen through anti-poisoning safety filter
        is_safe, filter_reason = self.poisoning_filter.evaluate(req)

        if auto_review:
            if is_safe:
                req.status = MemoryStatus.APPROVED
                req.approval_notes = "Auto-approved via safety heuristic filter."
            else:
                req.status = MemoryStatus.REJECTED
                req.approval_notes = filter_reason

        # 2. Persist in database
        async with UnitOfWork(self.session_factory) as uow:
            created_memory = await uow.memories.create(req)

            # Record in immutable audit log
            await uow.audit.append_audit_event(
                AuditEventCreateRequest(
                    event_id=f"aud-mem-{created_memory.id}",
                    engagement_id=req.engagement_id or "global",
                    correlation_id=corr_id,
                    event_type="agent_memory_recorded",
                    actor_type="AGENT",
                    actor_id=req.source_agent_id or req.role_id,
                    payload={
                        "memory_id": created_memory.id,
                        "role_id": req.role_id,
                        "key": req.key,
                        "target": req.target_domain_or_org,
                        "status": req.status.value,
                        "approval_notes": req.approval_notes,
                        "confidence": req.confidence_score,
                    },
                )
            )
            await uow.commit()

        # 3. Broadcast memory event
        await global_orchestrator.emit_event(
            event_type="agent_memory_recorded",
            correlation_id=corr_id,
            engagement_id=req.engagement_id,
            agent_id=req.source_agent_id,
            payload=created_memory.model_dump(),
        )

        logger.info(
            f"Recorded long-term memory [{created_memory.status.value}] for role '{req.role_id}': '{req.key}'",
            role_id=req.role_id,
            key=req.key,
            status=created_memory.status.value,
        )

        return created_memory

    async def approve_memory(
        self,
        memory_id: str,
        reviewer_id: str = "agent-ciso-01",
        notes: str = "Approved by CISO review",
        correlation_id: str = "",
    ) -> AgentMemoryResponse:
        """Explicitly approve a proposed memory entry for operational use."""
        corr_id = correlation_id or f"corr-appr-mem-{memory_id}"
        async with UnitOfWork(self.session_factory) as uow:
            updated = await uow.memories.update_status(
                memory_id=memory_id,
                status=MemoryStatus.APPROVED,
                approval_notes=notes,
            )
            if not updated:
                raise ValueError(f"Memory entry '{memory_id}' not found.")

            await uow.audit.append_audit_event(
                AuditEventCreateRequest(
                    event_id=f"aud-appr-mem-{memory_id[:8]}",
                    engagement_id=updated.engagement_id or "global",
                    correlation_id=corr_id,
                    event_type="agent_memory_approved",
                    actor_type="AGENT",
                    actor_id=reviewer_id,
                    payload={"memory_id": memory_id, "notes": notes},
                )
            )
            await uow.commit()

        return updated

    async def reject_memory(
        self,
        memory_id: str,
        reviewer_id: str = "agent-ciso-01",
        reason: str = "Rejected by CISO review",
        correlation_id: str = "",
    ) -> AgentMemoryResponse:
        """Reject a proposed memory entry."""
        corr_id = correlation_id or f"corr-rej-mem-{memory_id}"
        async with UnitOfWork(self.session_factory) as uow:
            updated = await uow.memories.update_status(
                memory_id=memory_id,
                status=MemoryStatus.REJECTED,
                approval_notes=reason,
            )
            if not updated:
                raise ValueError(f"Memory entry '{memory_id}' not found.")

            await uow.audit.append_audit_event(
                AuditEventCreateRequest(
                    event_id=f"aud-rej-mem-{memory_id[:8]}",
                    engagement_id=updated.engagement_id or "global",
                    correlation_id=corr_id,
                    event_type="agent_memory_rejected",
                    actor_type="AGENT",
                    actor_id=reviewer_id,
                    payload={"memory_id": memory_id, "reason": reason},
                )
            )
            await uow.commit()

        return updated

    async def get_relevant_memories(
        self,
        role_id: str,
        target: str,
        engagement_id: str | None = None,
        memory_type: MemoryType | str | None = None,
        limit: int = 10,
    ) -> list[AgentMemoryResponse]:
        """Fetch validated long-term memories for a specialist role on a specific target."""
        async with UnitOfWork(self.session_factory) as uow:
            memories = await uow.memories.query_memories(
                role_id=role_id,
                target=target,
                engagement_id=engagement_id,
                memory_type=memory_type,
                status=MemoryStatus.APPROVED,
            )
            return memories[:limit]
