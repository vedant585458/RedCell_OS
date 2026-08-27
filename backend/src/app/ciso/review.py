"""CISO Finding Review and Report Approval Service enforcing quality gates before deliverable compilation."""

from datetime import UTC, datetime
from typing import Any, Literal

import jinja2
from pydantic import BaseModel, Field

from app.ciso.prompts import CISO_FINDING_REVIEW_PROMPT, CISO_SYSTEM_PROMPT
from app.core.logging import get_logger
from app.domain.approval import ApprovalDecisionRequest, ApprovalRequestSchema, ApprovalStatus
from app.domain.audit import AuditEventCreateRequest
from app.domain.communication import MessageCreateRequest, MessageType
from app.domain.finding import FindingResponse, FindingStatus
from app.llm.interface import AgentBrain
from app.orchestrator.core import global_orchestrator
from app.repositories.unit_of_work import UnitOfWork

logger = get_logger("ciso.review")


class FindingQualityReport(BaseModel):
    """Quality scorecard and approval decision issued by CISO judge."""

    finding_id: str
    decision: Literal["APPROVED", "REJECTED_NEEDS_REWORK", "REJECTED_FALSE_POSITIVE"]
    quality_score: float = Field(ge=0.0, le=10.0, description="Overall quality score (0-10)")
    evidence_sufficient: bool = Field(description="Whether proof-of-concept evidence is sufficient")
    remediation_actionable: bool = Field(
        description="Whether remediation guidance is practical and actionable"
    )
    cvss_score_accurate: bool = Field(description="Whether CVSS score is accurately calculated")
    feedback_to_agent: str = Field(
        default="", description="Detailed constructive feedback sent to discovering agent"
    )
    reviewed_by: str = Field(default="agent-ciso-01")
    timestamp_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class CisoFindingReviewService:
    """CISO quality assurance service reviewing findings, creating Approval entities, and routing rework."""

    def __init__(self, session_factory: Any, brain: AgentBrain) -> None:
        self.session_factory = session_factory
        self.brain = brain
        self.template = jinja2.Template(CISO_FINDING_REVIEW_PROMPT)

    async def review_finding(self, finding_id: str) -> FindingQualityReport:
        """Review an individual finding against the CISO quality rubric and issue a binding approval decision."""
        # 1. Fetch finding with linked evidence and risk score
        async with UnitOfWork(self.session_factory) as uow:
            finding: FindingResponse | None = await uow.findings.get_finding_response(finding_id)

        if not finding:
            raise ValueError(f"Finding '{finding_id}' not found")

        # 2. Render prompt and invoke CISO AgentBrain
        rendered_prompt = self.template.render(finding=finding.model_dump())

        logger.info(
            "CISO reviewing finding quality",
            finding_id=finding_id,
            title=finding.title,
            severity=finding.severity,
        )

        try:
            response = await self.brain.generate(
                prompt=rendered_prompt,
                system_prompt=CISO_SYSTEM_PROMPT,
                response_schema=FindingQualityReport,
                temperature=0.1,
            )

            if response.structured_data and isinstance(
                response.structured_data, FindingQualityReport
            ):
                report: FindingQualityReport = response.structured_data
            else:
                report = FindingQualityReport.model_validate_json(response.content)

        except Exception as err:
            logger.warning(
                f"LLM review failed for finding '{finding_id}': {err}. Using deterministic fallback evaluation."
            )
            report = self._fallback_evaluation(finding, error_reason=str(err))

        # 3. Transactionally persist decision, update finding status, and route feedback
        async with UnitOfWork(self.session_factory) as uow:
            # Create formal Approval entity tracking CISO quality sign-off
            approval_gate_id = f"gate-ciso-rev-{finding_id}"
            await uow.approvals.create_request(
                ApprovalRequestSchema(
                    id=approval_gate_id,
                    engagement_id=finding.engagement_id,
                    task_id=finding.task_id,
                    agent_id="agent-ciso-01",
                    category="CISO_REPORT_QUALITY_GATE",
                    target_uri=finding.target_endpoint,
                    risk_description=f"CISO Quality Review for finding '{finding.title}'",
                    proposed_command="include_in_final_report",
                )
            )

            if report.decision == "APPROVED":
                # Advance finding to REPORTED status
                await uow.findings.update_status(finding_id, FindingStatus.REPORTED)

                # Record Approval as GRANTED
                await uow.approvals.decide_gate(
                    approval_gate_id,
                    ApprovalDecisionRequest(
                        decision=ApprovalStatus.GRANTED,
                        operator_id="agent-ciso-01",
                        decision_reason=f"Approved with quality score {report.quality_score}/10: {report.feedback_to_agent}",
                    ),
                )
            else:
                # Revert finding to DRAFT status for rework
                await uow.findings.update_status(finding_id, FindingStatus.DRAFT)

                # Record Approval as REJECTED
                await uow.approvals.decide_gate(
                    approval_gate_id,
                    ApprovalDecisionRequest(
                        decision=ApprovalStatus.REJECTED,
                        operator_id="agent-ciso-01",
                        decision_reason=f"Rejected ({report.decision}): {report.feedback_to_agent}",
                    ),
                )

                # Route feedback message back to discovering specialist agent
                await uow.messages.send_message(
                    MessageCreateRequest(
                        id=f"msg-rework-{finding_id}",
                        engagement_id=finding.engagement_id,
                        sender_agent_id="agent-ciso-01",
                        recipient_agent_id=finding.agent_id,
                        task_id=finding.task_id,
                        message_type=MessageType.ALERT,
                        content=(
                            f"Finding '{finding.title}' ({finding_id}) was rejected during CISO quality review. "
                            f"Feedback: {report.feedback_to_agent}. Please collect additional evidence/clarify steps and resubmit."
                        ),
                        metadata={"quality_report": report.model_dump()},
                    )
                )

            # Record audit entry
            await uow.audit.append_audit_event(
                AuditEventCreateRequest(
                    event_id=f"aud-rev-{finding_id}",
                    engagement_id=finding.engagement_id,
                    correlation_id=f"corr-rev-{finding_id}",
                    event_type="finding_reviewed",
                    actor_type="AGENT",
                    actor_id="agent-ciso-01",
                    payload=report.model_dump(),
                )
            )

            await uow.commit()

        # 4. Emit real-time decision event
        event_name = "finding_approved" if report.decision == "APPROVED" else "finding_rejected"
        await global_orchestrator.emit_event(
            event_type=event_name,
            correlation_id=f"corr-rev-{finding_id}",
            engagement_id=finding.engagement_id,
            agent_id="agent-ciso-01",
            task_id=finding.task_id,
            payload=report.model_dump(),
        )

        logger.info(
            f"CISO finding review complete: {report.decision}",
            finding_id=finding_id,
            decision=report.decision,
            score=report.quality_score,
        )

        return report

    async def review_engagement_findings(self, engagement_id: str) -> list[FindingQualityReport]:
        """Review all un-reviewed findings in an engagement."""
        async with UnitOfWork(self.session_factory) as uow:
            findings = await uow.findings.list_by_engagement(engagement_id)

        reports: list[FindingQualityReport] = []
        for f in findings:
            report = await self.review_finding(f.finding_id)
            reports.append(report)

        return reports

    def _fallback_evaluation(
        self, finding: FindingResponse, error_reason: str
    ) -> FindingQualityReport:
        """Deterministic evaluation fallback based on presence of evidence artifacts and CVSS score."""
        has_evidence = len(finding.evidence) > 0
        has_risk = finding.risk_score is not None
        has_remediation = bool(
            finding.remediation_guidance and len(finding.remediation_guidance) > 10
        )

        if has_evidence and has_risk and has_remediation:
            return FindingQualityReport(
                finding_id=finding.finding_id,
                decision="APPROVED",
                quality_score=8.0,
                evidence_sufficient=True,
                remediation_actionable=True,
                cvss_score_accurate=True,
                feedback_to_agent="Approved via deterministic quality evaluation.",
            )

        return FindingQualityReport(
            finding_id=finding.finding_id,
            decision="REJECTED_NEEDS_REWORK",
            quality_score=4.0,
            evidence_sufficient=has_evidence,
            remediation_actionable=has_remediation,
            cvss_score_accurate=has_risk,
            feedback_to_agent=f"Finding lacks required evidence artifacts or detailed remediation: {error_reason}",
        )
