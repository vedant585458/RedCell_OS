"""CISO intake interpreter service translating high-level engagement text into structured objectives via AgentBrain."""

from typing import Literal

import jinja2
from pydantic import BaseModel, Field

from app.ciso.prompts import CISO_INTERPRETATION_USER_PROMPT, CISO_SYSTEM_PROMPT
from app.core.logging import get_logger
from app.domain.engagement import RulesOfEngagementSchema, TargetScopeSchema
from app.llm.interface import AgentBrain
from app.llm.models import ChatMessage

logger = get_logger("ciso.interpreter")


class InterpretedObjective(BaseModel):
    """Structured objective extracted by CISO intelligence from engagement scope."""

    objective_id: str = Field(description="Unique objective ID (e.g. OBJ-01)")
    title: str = Field(description="Action-oriented title of the objective")
    department_id: str = Field(
        description="Assigned department (e.g. dept_recon, dept_vulnerability)"
    )
    assigned_role: str = Field(description="Specialist role required (e.g. role_web_discovery)")
    target_focus: str = Field(description="Specific asset focus within allowlist")
    target_endpoints: list[str] = Field(
        default_factory=list, description="Explicit target IPs, CIDRs, or URLs"
    )
    priority: int = Field(default=2, ge=1, le=4, description="Priority level 1-4")
    estimated_intensity: Literal[
        "passive_recon",
        "active_recon",
        "vulnerability_verification",
        "safe_exploitation",
    ] = Field(default="passive_recon")
    requires_human_approval: bool = Field(
        default=False, description="Whether objective requires HITL gate"
    )
    justification: str = Field(
        default="", description="Strategic justification aligning with client goals"
    )


class CisoInterpretationResult(BaseModel):
    """Complete structured interpretation output from CISO intelligence layer."""

    engagement_id: str
    executive_summary: str = Field(description="Executive analysis of engagement goals and risks")
    assessed_risk_posture: str = Field(description="Initial risk posture assessment")
    objectives: list[InterpretedObjective] = Field(
        description="Ordered list of departmental objectives"
    )
    scope_compliance_verified: bool = Field(default=True)
    flagged_ambiguities: list[str] = Field(default_factory=list)
    escalate_to_human: bool = Field(default=False)
    escalation_reason: str | None = Field(default=None)


class CisoIntakeInterpreter:
    """CISO AI reasoning service extracting validated, anti-hallucinated objectives from engagement text."""

    def __init__(self, brain: AgentBrain) -> None:
        self.brain = brain
        self.template = jinja2.Template(CISO_INTERPRETATION_USER_PROMPT)

    async def interpret_engagement(
        self,
        engagement_id: str,
        title: str,
        organization: str,
        high_level_objective: str,
        target_scope: TargetScopeSchema,
        rules_of_engagement: RulesOfEngagementSchema,
        max_retries: int = 2,
    ) -> CisoInterpretationResult:
        """Execute LLM prompt pipeline to extract structured objectives with schema validation and scope cross-check."""
        rendered_prompt = self.template.render(
            engagement_id=engagement_id,
            title=title,
            organization=organization,
            high_level_objective=high_level_objective,
            target_scope=target_scope.model_dump(),
            rules_of_engagement=rules_of_engagement.model_dump(),
        )

        history: list[ChatMessage] = []
        last_error_detail: str | None = None

        for attempt in range(max_retries + 1):
            try:
                current_prompt = rendered_prompt
                if attempt > 0 and last_error_detail:
                    current_prompt += (
                        f"\n\n[SELF-CORRECTION NOTICE - ATTEMPT {attempt + 1}]\n"
                        f"Your previous output failed schema validation: {last_error_detail}\n"
                        f"Correct the formatting and return strictly valid JSON conforming to CisoInterpretationResult."
                    )

                logger.info(
                    "Invoking CISO AgentBrain for scope interpretation",
                    engagement_id=engagement_id,
                    attempt=attempt + 1,
                )

                response = await self.brain.generate(
                    prompt=current_prompt,
                    system_prompt=CISO_SYSTEM_PROMPT,
                    history=history,
                    response_schema=CisoInterpretationResult,
                    temperature=0.2,
                )

                if response.structured_data and isinstance(
                    response.structured_data, CisoInterpretationResult
                ):
                    result: CisoInterpretationResult = response.structured_data
                    return self._cross_check_scope_compliance(result, target_scope)

                # If raw text returned, validate with Pydantic
                result = CisoInterpretationResult.model_validate_json(response.content)
                return self._cross_check_scope_compliance(result, target_scope)

            except Exception as err:
                last_error_detail = str(err)
                logger.warning(
                    f"CISO interpretation attempt {attempt + 1} failed: {err}",
                    engagement_id=engagement_id,
                )

        # Fallback escalation if all LLM retries fail
        logger.error(
            "CISO interpretation exhausted all retries. Escalating to human operator.",
            engagement_id=engagement_id,
        )
        return self._create_fallback_escalation(
            engagement_id=engagement_id,
            high_level_objective=high_level_objective,
            target_scope=target_scope,
            reason=f"LLM schema validation failed after {max_retries + 1} attempts: {last_error_detail}",
        )

    def _cross_check_scope_compliance(
        self,
        result: CisoInterpretationResult,
        scope: TargetScopeSchema,
    ) -> CisoInterpretationResult:
        """Cross-check LLM proposed objectives against physical Scope allowlists to eliminate hallucinations."""
        allowed_targets = set(
            scope.allowed_ipv4_cidrs + scope.allowed_ipv6_cidrs + scope.allowed_domains
        )
        excluded_ips = set(scope.excluded_ipv4_cidrs + scope.excluded_domains)

        sanitized_objectives: list[InterpretedObjective] = []
        flagged_ambiguities = list(result.flagged_ambiguities)
        needs_escalation = result.escalate_to_human

        for obj in result.objectives:
            is_valid = True
            for endpoint in obj.target_endpoints:
                # 1. Check for explicit exclusion violation
                if endpoint in excluded_ips:
                    is_valid = False
                    flagged_ambiguities.append(
                        f"Objective '{obj.objective_id}' referenced explicitly EXCLUDED target '{endpoint}'."
                    )
                    needs_escalation = True
                # 2. Check if endpoint belongs to allowed target set (or partial allowlist match)
                elif allowed_targets and not any(
                    endpoint in allowed or allowed in endpoint for allowed in allowed_targets
                ):
                    flagged_ambiguities.append(
                        f"Objective '{obj.objective_id}' referenced unverified target '{endpoint}'."
                    )

            if is_valid:
                sanitized_objectives.append(obj)

        return CisoInterpretationResult(
            engagement_id=result.engagement_id,
            executive_summary=result.executive_summary,
            assessed_risk_posture=result.assessed_risk_posture,
            objectives=sanitized_objectives,
            scope_compliance_verified=len(flagged_ambiguities) == 0,
            flagged_ambiguities=flagged_ambiguities,
            escalate_to_human=needs_escalation,
            escalation_reason=result.escalation_reason
            or ("Out-of-scope targets flagged during cross-check." if needs_escalation else None),
        )

    def _create_fallback_escalation(
        self,
        engagement_id: str,
        high_level_objective: str,
        target_scope: TargetScopeSchema,
        reason: str,
    ) -> CisoInterpretationResult:
        """Create a safe deterministic fallback objective list with mandatory human escalation."""
        primary_target = (
            target_scope.allowed_ipv4_cidrs[0]
            if target_scope.allowed_ipv4_cidrs
            else (target_scope.allowed_domains[0] if target_scope.allowed_domains else "127.0.0.1")
        )

        fallback_obj = InterpretedObjective(
            objective_id="OBJ-01",
            title="Baseline Reconnaissance & Attack Surface Discovery",
            department_id="dept_recon",
            assigned_role="role_web_discovery",
            target_focus=f"Target perimeter on {primary_target}",
            target_endpoints=[primary_target],
            priority=3,
            estimated_intensity="passive_recon",
            requires_human_approval=False,
            justification="Default fallback objective created for operator review.",
        )

        return CisoInterpretationResult(
            engagement_id=engagement_id,
            executive_summary=f"CISO Automated Interpretation Paused: {high_level_objective}",
            assessed_risk_posture="MODERATE — Awaiting operator scope confirmation.",
            objectives=[fallback_obj],
            scope_compliance_verified=False,
            flagged_ambiguities=[reason],
            escalate_to_human=True,
            escalation_reason=reason,
        )
