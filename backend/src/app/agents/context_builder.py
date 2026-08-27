"""Agent Working-Memory Context Builder with pinned scope/ROE, token budget management, and relevance-weighted truncation."""

import json
import math
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.domain.agent_memory import AgentMemoryResponse, MemoryStatus
from app.domain.communication import MessageResponse
from app.domain.engagement import EngagementResponse
from app.domain.finding import FindingResponse, FindingSeverity
from app.domain.task import TaskResponse
from app.llm.models import ChatMessage
from app.repositories.unit_of_work import UnitOfWork

logger = get_logger("agents.context_builder")

DEFAULT_CONTEXT_TOKEN_BUDGET = 4000
CHARS_PER_TOKEN = 3.8  # Standard heuristic for English / code / JSON tokens


def estimate_tokens(text: str) -> int:
    """Fast, accurate token estimation heuristic based on character length."""
    if not text:
        return 0
    return max(1, math.ceil(len(text) / CHARS_PER_TOKEN))


class RankedContextItem(BaseModel):
    """Context item candidate scored for greedy token budget packing."""

    item_id: str
    category: str  # 'parent_task' | 'finding' | 'message'
    text_content: str
    estimated_tokens: int
    relevance_score: float = Field(ge=0.0, le=1.0)
    recency_score: float = Field(ge=0.0, le=1.0)
    combined_weight: float = Field(ge=0.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentWorkingContext(BaseModel):
    """Assembled working memory context window ready for LLM consumption."""

    task_id: str
    agent_id: str
    engagement_id: str
    system_prompt: str = Field(description="Pinned role identity and capabilities")
    scope_and_roe: str = Field(description="Pinned Scope & Rules of Engagement constraints")
    task_details: str = Field(description="Pinned target parameters and task objective")
    parent_chain_summaries: list[str] = Field(default_factory=list)
    persistent_memories: list[dict[str, Any]] = Field(default_factory=list)
    relevant_findings: list[dict[str, Any]] = Field(default_factory=list)
    recent_messages: list[dict[str, Any]] = Field(default_factory=list)
    estimated_tokens: int
    token_budget: int
    is_truncated: bool
    truncated_items_count: int
    assembled_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_chat_messages(self) -> list[ChatMessage]:
        """Convert assembled working memory into standardized ChatMessage format for AgentBrain."""
        # System Message: Role prompt + Pinned Scope/ROE
        system_body = (
            f"{self.system_prompt}\n\n"
            f"=== AUTHORIZED SCOPE & RULES OF ENGAGEMENT (STRICT ENFORCEMENT) ===\n"
            f"{self.scope_and_roe}"
        )

        # User Message: Task context, Ancestry, Persistent Role Memory, Findings, and Messages
        user_sections: list[str] = [f"=== CURRENT TASK OBJECTIVE ===\n{self.task_details}"]

        if self.parent_chain_summaries:
            ancestors_str = "\n".join(f"- {anc}" for anc in self.parent_chain_summaries)
            user_sections.append(f"=== PARENT MISSION DAG CONTEXT ===\n{ancestors_str}")

        if self.persistent_memories:
            memories_str = "\n".join(
                f"- [{m.get('memory_type', 'LEARNED')}] {m.get('key')}: {m.get('content')} "
                f"(Confidence: {m.get('confidence_score', 0.8):.2f})"
                for m in self.persistent_memories
            )
            user_sections.append(
                f"=== PERSISTENT ROLE MEMORY (LEARNED OBSERVATIONS) ===\n{memories_str}"
            )

        if self.relevant_findings:
            findings_str = "\n".join(
                f"- [{f.get('severity', 'HIGH')}] {f.get('title')}: {f.get('target_endpoint')} "
                f"(CVSS: {f.get('cvss_score', 'N/A')})"
                for f in self.relevant_findings
            )
            user_sections.append(f"=== PRIOR RELEVANT DISCOVERIES ===\n{findings_str}")

        if self.recent_messages:
            messages_str = "\n".join(
                f"- [{m.get('sender')} -> {m.get('recipient', 'ALL')}]: {m.get('content')}"
                for m in self.recent_messages
            )
            user_sections.append(f"=== INTER-AGENT BRIEFINGS & MESSAGES ===\n{messages_str}")

        user_body = "\n\n".join(user_sections)

        return [
            ChatMessage(role="system", content=system_body),
            ChatMessage(role="user", content=user_body),
        ]

    def render_full_prompt(self) -> str:
        """Render consolidated prompt string."""
        msgs = self.to_chat_messages()
        return f"[SYSTEM]\n{msgs[0].content}\n\n[USER]\n{msgs[1].content}"


class ContextBuilder:
    """Service assembling task working memory, pinning Scope/ROE, and packing relevant context within token budgets."""

    def __init__(
        self,
        session_factory: Any,
        default_token_budget: int = DEFAULT_CONTEXT_TOKEN_BUDGET,
    ) -> None:
        self.session_factory = session_factory
        self.default_token_budget = default_token_budget

    async def build_context(
        self,
        agent_id: str,
        task_id: str,
        token_budget: int | None = None,
        max_messages: int = 15,
        max_findings: int = 15,
    ) -> AgentWorkingContext:
        """Assemble working memory context for an agent executing a task.

        Technical Decisions:
        1. Scope and ROE are PINNED: Never dropped or truncated.
        2. Dynamic truncation prioritizes relevance score + recency over raw chronological order.
        """
        budget = token_budget if token_budget is not None else self.default_token_budget

        async with UnitOfWork(self.session_factory) as uow:
            # 1. Fetch Task, Agent, Role, and Engagement
            task_resp = await uow.tasks.get_task_response(task_id)
            if not task_resp:
                raise ValueError(f"Task '{task_id}' not found in database.")

            agent_resp = await uow.agents.get_by_id(agent_id)
            if not agent_resp:
                raise ValueError(f"Agent '{agent_id}' not found in database.")

            role_model = await uow.roles.get_by_id(agent_resp.role_id)
            role_resp = role_model.to_response() if role_model else None
            role_desc = (
                role_resp.description if role_resp else f"Specialist agent {agent_resp.role_id}"
            )
            role_caps = role_resp.capabilities if role_resp else []

            engagement_model = await uow.engagements.get_by_id(task_resp.engagement_id)
            if not engagement_model:
                raise ValueError(f"Engagement '{task_resp.engagement_id}' not found.")
            engagement_resp = engagement_model.to_response()

            # 2. Build PINNED sections (Cannot be truncated under any circumstance)
            system_prompt = self._build_pinned_system_prompt(
                agent_id=agent_resp.id,
                display_name=agent_resp.display_name,
                role_id=agent_resp.role_id,
                description=role_desc,
                capabilities=role_caps,
            )
            scope_and_roe = self._build_pinned_scope_and_roe(engagement_resp)
            task_details = self._build_pinned_task_details(task_resp)

            pinned_tokens = (
                estimate_tokens(system_prompt)
                + estimate_tokens(scope_and_roe)
                + estimate_tokens(task_details)
            )

            # Available budget for dynamic truncatable items
            remaining_budget = max(0, budget - pinned_tokens)

            # 3. Gather Ancestor Parent Chain
            parent_chain_items = await self._gather_parent_chain(task_resp, uow)

            # 4. Gather Prior Findings
            findings = await uow.findings.list_by_engagement(task_resp.engagement_id)

            # 5. Gather Recent Messages
            task_messages = await uow.messages.list_by_task(task_id)
            eng_messages = await uow.messages.list_by_engagement(task_resp.engagement_id)
            combined_messages = self._deduplicate_messages(task_messages + eng_messages)

            # 6. Gather Persistent Long-Term Role Memories
            target_endpoint = str(
                task_resp.input_context.get(
                    "target", task_resp.input_context.get("target_endpoint", "")
                )
            )
            persistent_memories = await uow.memories.query_memories(
                role_id=agent_resp.role_id,
                target=target_endpoint or engagement_resp.organization,
                engagement_id=task_resp.engagement_id,
                status=MemoryStatus.APPROVED,
            )

        # 7. Rank Dynamic Context Candidates (Technical Decision: Relevance + Recency Scoring)
        ranked_items = self._rank_candidates(
            parent_chain=parent_chain_items,
            memories=persistent_memories,
            findings=findings[:max_findings],
            messages=combined_messages[:max_messages],
            task_id=task_id,
            target_endpoint=target_endpoint,
        )

        # 8. Greedy Packing within Remaining Token Budget
        (
            packed_parents,
            packed_memories,
            packed_findings,
            packed_messages,
            truncated_count,
        ) = self._pack_items(
            ranked_items=ranked_items,
            available_budget=remaining_budget,
        )

        total_estimated_tokens = (
            pinned_tokens
            + sum(estimate_tokens(p) for p in packed_parents)
            + sum(estimate_tokens(json.dumps(m)) for m in packed_memories)
            + sum(estimate_tokens(json.dumps(f)) for f in packed_findings)
            + sum(estimate_tokens(json.dumps(msg)) for msg in packed_messages)
        )

        return AgentWorkingContext(
            task_id=task_id,
            agent_id=agent_id,
            engagement_id=task_resp.engagement_id,
            system_prompt=system_prompt,
            scope_and_roe=scope_and_roe,
            task_details=task_details,
            parent_chain_summaries=packed_parents,
            persistent_memories=packed_memories,
            relevant_findings=packed_findings,
            recent_messages=packed_messages,
            estimated_tokens=total_estimated_tokens,
            token_budget=budget,
            is_truncated=truncated_count > 0,
            truncated_items_count=truncated_count,
        )

    def _build_pinned_system_prompt(
        self,
        agent_id: str,
        display_name: str,
        role_id: str,
        description: str,
        capabilities: list[str],
    ) -> str:
        caps_formatted = ", ".join(capabilities) if capabilities else "General Penetration Testing"
        return (
            f"You are {display_name} ({agent_id} | {role_id}), an autonomous specialist AI Employee operating in RedCell_OS.\n"
            f"Role Purpose: {description}\n"
            f"Authorized Specialist Capabilities: {caps_formatted}\n"
            f"Mandate: Execute tactical penetration testing actions strictly adhering to Rules of Engagement."
        )

    def _build_pinned_scope_and_roe(self, engagement: EngagementResponse) -> str:
        """Pinned: Scope CIDRs, Domains, Ports, and Exclusions are never truncated."""
        scope = engagement.target_scope
        roe = engagement.rules_of_engagement

        allowed_cidrs = ", ".join(scope.allowed_ipv4_cidrs) or "None specified"
        allowed_domains = ", ".join(scope.allowed_domains) or "None specified"
        allowed_ports = ", ".join(scope.allowed_ports) or "Default (80, 443, 8088)"
        excluded_cidrs = ", ".join(scope.excluded_ipv4_cidrs) or "None"
        excluded_domains = ", ".join(scope.excluded_domains) or "None"
        prohibited = ", ".join(roe.prohibited_actions) or "DENIAL_OF_SERVICE, PERMANENT_DESTRUCTION"
        intensity = roe.max_intensity

        return (
            f"- Organization: {engagement.organization}\n"
            f"- Authorized IPv4 Targets: [{allowed_cidrs}]\n"
            f"- Authorized Target Domains: [{allowed_domains}]\n"
            f"- Authorized Ports: [{allowed_ports}]\n"
            f"- FORBIDDEN Target Exclusions (HARD DENY): [{excluded_cidrs}], Domains: [{excluded_domains}]\n"
            f"- Max Offensive Intensity: {intensity.upper()}\n"
            f"- Prohibited Actions: [{prohibited}]\n"
            f"- Max Packet Rate: {roe.max_packets_per_sec} pps, Bandwidth Limit: {roe.max_bandwidth_kbps} kbps"
        )

    def _build_pinned_task_details(self, task: TaskResponse) -> str:
        """Pinned: Task Title, Priority, Parameters, and Target context."""
        ctx_str = json.dumps(task.input_context, indent=2) if task.input_context else "{}"
        return (
            f"- Task ID: {task.task_id}\n"
            f"- Title: {task.title}\n"
            f"- Description: {task.description or 'No additional description'}\n"
            f"- Priority Level: {task.priority} (1=Low, 2=Medium, 3=High, 4=Critical)\n"
            f"- Target Parameters:\n{ctx_str}"
        )

    async def _gather_parent_chain(self, task: TaskResponse, uow: UnitOfWork) -> list[TaskResponse]:
        """Walk parent pointers upstream to gather ancestor mission context."""
        chain: list[TaskResponse] = []
        current_parent_id = task.parent_task_id

        while current_parent_id:
            parent = await uow.tasks.get_task_response(current_parent_id)
            if not parent:
                break
            chain.append(parent)
            current_parent_id = parent.parent_task_id
            if len(chain) > 10:  # Circuit breaker
                break

        return chain

    def _deduplicate_messages(self, messages: list[MessageResponse]) -> list[MessageResponse]:
        seen = set()
        deduped = []
        for m in sorted(messages, key=lambda x: x.created_at, reverse=True):
            if m.id not in seen:
                seen.add(m.id)
                deduped.append(m)
        return deduped

    def _score_finding(self, finding: FindingResponse, target_endpoint: str) -> float:
        """Relevance scoring for security findings: endpoint match + severity weighting."""
        score = 0.3  # Base discovery value

        # Endpoint relevance
        if target_endpoint and target_endpoint.lower() in finding.target_endpoint.lower():
            score += 0.4
        elif finding.target_endpoint and finding.target_endpoint.lower() in target_endpoint.lower():
            score += 0.4

        # Severity boost
        if finding.severity == FindingSeverity.CRITICAL:
            score += 0.3
        elif finding.severity == FindingSeverity.HIGH:
            score += 0.2
        elif finding.severity == FindingSeverity.MEDIUM:
            score += 0.1

        return min(1.0, score)

    def _score_message(self, message: MessageResponse, task_id: str) -> float:
        """Relevance scoring for inter-agent messages: task context linkage."""
        if message.task_id == task_id:
            return 0.9  # Directly linked to current task
        if message.message_type == "TASK_HANDOFF":
            return 0.8
        if message.message_type == "ALERT":
            return 0.7
        return 0.4

    def _rank_candidates(
        self,
        parent_chain: list[TaskResponse],
        memories: list[AgentMemoryResponse],
        findings: list[FindingResponse],
        messages: list[MessageResponse],
        task_id: str,
        target_endpoint: str,
    ) -> list[RankedContextItem]:
        """Rank all dynamic candidates by combined weight = (0.6 * relevance) + (0.4 * recency)."""
        candidates: list[RankedContextItem] = []

        # 1. Parent Ancestor Chain
        for idx, anc in enumerate(parent_chain):
            text = f"Parent Task '{anc.task_id}': {anc.title} (Status: {anc.status.value})"
            rel = 0.8 / (idx + 1)
            rec = 0.9 / (idx + 1)
            weight = (0.6 * rel) + (0.4 * rec)
            candidates.append(
                RankedContextItem(
                    item_id=f"parent-{anc.task_id}",
                    category="parent_task",
                    text_content=text,
                    estimated_tokens=estimate_tokens(text),
                    relevance_score=rel,
                    recency_score=rec,
                    combined_weight=weight,
                    metadata={"summary": text},
                )
            )

        # 2. Persistent Role Memories (Learned patterns across tasks/engagements)
        for idx, mem in enumerate(memories):
            mem_dict = {
                "memory_id": mem.id,
                "role_id": mem.role_id,
                "memory_type": mem.memory_type.value,
                "key": mem.key,
                "content": mem.content,
                "confidence_score": mem.confidence_score,
            }
            text = f"[{mem.memory_type.value}] {mem.key}: {mem.content}"
            rel = mem.confidence_score
            if target_endpoint and target_endpoint.lower() in mem.target_domain_or_org.lower():
                rel = min(1.0, rel + 0.2)
            rec = max(0.5, 1.0 - (idx * 0.05))
            weight = (0.6 * rel) + (0.4 * rec)
            candidates.append(
                RankedContextItem(
                    item_id=f"mem-{mem.id}",
                    category="persistent_memory",
                    text_content=text,
                    estimated_tokens=estimate_tokens(text),
                    relevance_score=rel,
                    recency_score=rec,
                    combined_weight=weight,
                    metadata=mem_dict,
                )
            )

        # 3. Findings
        for idx, f in enumerate(findings):
            f_dict = {
                "finding_id": f.finding_id,
                "title": f.title,
                "severity": f.severity.value,
                "target_endpoint": f.target_endpoint,
                "cvss_score": f.risk_score.cvss_v31_base_score if f.risk_score else None,
            }
            text = json.dumps(f_dict)
            rel = self._score_finding(f, target_endpoint)
            # Recency decay across finding index
            rec = max(0.2, 1.0 - (idx * 0.05))
            weight = (0.6 * rel) + (0.4 * rec)
            candidates.append(
                RankedContextItem(
                    item_id=f"finding-{f.finding_id}",
                    category="finding",
                    text_content=text,
                    estimated_tokens=estimate_tokens(text),
                    relevance_score=rel,
                    recency_score=rec,
                    combined_weight=weight,
                    metadata=f_dict,
                )
            )

        # 4. Messages
        for idx, msg in enumerate(messages):
            msg_dict = {
                "message_id": msg.id,
                "sender": msg.sender_agent_id,
                "recipient": msg.recipient_agent_id,
                "type": msg.message_type.value,
                "content": msg.content,
                "created_at": msg.created_at,
            }
            text = json.dumps(msg_dict)
            rel = self._score_message(msg, task_id)
            rec = max(0.1, 1.0 - (idx * 0.08))
            weight = (0.6 * rel) + (0.4 * rec)
            candidates.append(
                RankedContextItem(
                    item_id=f"msg-{msg.id}",
                    category="message",
                    text_content=text,
                    estimated_tokens=estimate_tokens(text),
                    relevance_score=rel,
                    recency_score=rec,
                    combined_weight=weight,
                    metadata=msg_dict,
                )
            )

        # Sort candidates strictly by combined weight descending
        candidates.sort(key=lambda x: x.combined_weight, reverse=True)
        return candidates

    def _pack_items(
        self,
        ranked_items: list[RankedContextItem],
        available_budget: int,
    ) -> tuple[
        list[str],
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[dict[str, Any]],
        int,
    ]:
        """Greedily pack ranked dynamic items into available budget."""
        packed_parents: list[str] = []
        packed_memories: list[dict[str, Any]] = []
        packed_findings: list[dict[str, Any]] = []
        packed_messages: list[dict[str, Any]] = []

        spent_tokens = 0
        truncated_count = 0

        for item in ranked_items:
            if spent_tokens + item.estimated_tokens <= available_budget:
                spent_tokens += item.estimated_tokens
                if item.category == "parent_task":
                    packed_parents.append(item.metadata.get("summary", item.text_content))
                elif item.category == "persistent_memory":
                    packed_memories.append(item.metadata)
                elif item.category == "finding":
                    packed_findings.append(item.metadata)
                elif item.category == "message":
                    packed_messages.append(item.metadata)
            else:
                truncated_count += 1

        return (
            packed_parents,
            packed_memories,
            packed_findings,
            packed_messages,
            truncated_count,
        )
