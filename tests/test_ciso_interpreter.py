"""Unit tests for CisoIntakeInterpreter prompt pipeline, schema validation, and scope cross-checking."""

import pytest
from app.ciso.intake_interpreter import (
    CisoIntakeInterpreter,
    CisoInterpretationResult,
    InterpretedObjective,
)
from app.domain.engagement import RulesOfEngagementSchema, TargetScopeSchema
from app.llm.mock_brain import MockAgentBrain
from app.llm.models import BrainResponse, BrainUsage


@pytest.mark.asyncio
async def test_ciso_interpretation_valid_scripted_response():
    expected_result = CisoInterpretationResult(
        engagement_id="eng-mvp-001",
        executive_summary="Authorized black-box assessment targeting staging portal perimeter.",
        assessed_risk_posture="MODERATE",
        objectives=[
            InterpretedObjective(
                objective_id="OBJ-01",
                title="Web Attack Surface Discovery",
                department_id="dept_recon",
                assigned_role="role_web_discovery",
                target_focus="Staging portal HTTP endpoints",
                target_endpoints=["127.0.0.1/32"],
                priority=3,
                estimated_intensity="passive_recon",
                requires_human_approval=False,
                justification="Map exposed routes on port 8088.",
            ),
            InterpretedObjective(
                objective_id="OBJ-02",
                title="Debug Configuration Exposure Validation",
                department_id="dept_vulnerability",
                assigned_role="role_web_vuln_assessor",
                target_focus="Discovered debug endpoint",
                target_endpoints=["127.0.0.1/32"],
                priority=3,
                estimated_intensity="vulnerability_verification",
                requires_human_approval=True,
                justification="Verify potential credential leakage.",
            ),
        ],
        scope_compliance_verified=True,
    )

    mock_brain = MockAgentBrain(
        scripted_responses={CisoInterpretationResult: expected_result}
    )
    interpreter = CisoIntakeInterpreter(brain=mock_brain)

    scope = TargetScopeSchema(
        allowed_ipv4_cidrs=["127.0.0.1/32"],
        allowed_ports=["8088"],
        excluded_ipv4_cidrs=[],
    )
    roe = RulesOfEngagementSchema(max_intensity="vulnerability_verification")

    result = await interpreter.interpret_engagement(
        engagement_id="eng-mvp-001",
        title="MVP Pentest",
        organization="Acme Labs",
        high_level_objective="Test staging portal",
        target_scope=scope,
        rules_of_engagement=roe,
    )

    assert result.engagement_id == "eng-mvp-001"
    assert len(result.objectives) == 2
    assert result.objectives[0].department_id == "dept_recon"
    assert result.objectives[1].requires_human_approval is True
    assert result.scope_compliance_verified is True
    assert result.escalate_to_human is False


@pytest.mark.asyncio
async def test_ciso_interpretation_anti_hallucination_scope_cross_check():
    # LLM hallucinates an excluded target in an objective
    hallucinated_result = CisoInterpretationResult(
        engagement_id="eng-mvp-002",
        executive_summary="Assessment plan",
        assessed_risk_posture="HIGH",
        objectives=[
            InterpretedObjective(
                objective_id="OBJ-01",
                title="Prohibited Gateway Scan",
                department_id="dept_recon",
                assigned_role="role_active_network_recon",
                target_focus="Forbidden Gateway",
                target_endpoints=["10.100.20.1/32"],  # Explicitly excluded!
                priority=4,
                estimated_intensity="active_recon",
                requires_human_approval=False,
            ),
            InterpretedObjective(
                objective_id="OBJ-02",
                title="Allowed Target Scan",
                department_id="dept_recon",
                assigned_role="role_web_discovery",
                target_focus="Staging Server",
                target_endpoints=["10.100.20.50/32"],  # Allowed
                priority=2,
                estimated_intensity="passive_recon",
                requires_human_approval=False,
            ),
        ],
    )

    mock_brain = MockAgentBrain(
        scripted_responses={CisoInterpretationResult: hallucinated_result}
    )
    interpreter = CisoIntakeInterpreter(brain=mock_brain)

    scope = TargetScopeSchema(
        allowed_ipv4_cidrs=["10.100.20.0/24"],
        excluded_ipv4_cidrs=["10.100.20.1/32"],  # Gateway excluded!
        allowed_ports=["80", "443"],
    )
    roe = RulesOfEngagementSchema()

    result = await interpreter.interpret_engagement(
        engagement_id="eng-mvp-002",
        title="Perimeter Test",
        organization="Acme",
        high_level_objective="Test network",
        target_scope=scope,
        rules_of_engagement=roe,
    )

    # Hallucinated objective should be pruned, and escalation flagged
    assert len(result.objectives) == 1
    assert result.objectives[0].objective_id == "OBJ-02"
    assert result.scope_compliance_verified is False
    assert result.escalate_to_human is True
    assert any(
        "EXCLUDED target '10.100.20.1/32'" in amb for amb in result.flagged_ambiguities
    )


@pytest.mark.asyncio
async def test_ciso_interpretation_fallback_on_unhandled_failure():
    # Mock brain that generates invalid data failing validation
    class FailingBrain(MockAgentBrain):
        async def generate(self, *args, **kwargs) -> BrainResponse:
            return BrainResponse(
                content="Not valid JSON at all",
                usage=BrainUsage(total_tokens=10),
                model="failing-model",
            )

    failing_brain = FailingBrain()
    interpreter = CisoIntakeInterpreter(brain=failing_brain)

    scope = TargetScopeSchema(
        allowed_ipv4_cidrs=["127.0.0.1/32"],
        allowed_ports=["8088"],
    )
    roe = RulesOfEngagementSchema()

    result = await interpreter.interpret_engagement(
        engagement_id="eng-fallback-01",
        title="Fallback Pentest",
        organization="Acme",
        high_level_objective="Check web server",
        target_scope=scope,
        rules_of_engagement=roe,
        max_retries=1,
    )

    # Must cleanly return fallback objective with escalate_to_human=True
    assert result.engagement_id == "eng-fallback-01"
    assert result.escalate_to_human is True
    assert len(result.objectives) == 1
    assert (
        result.objectives[0].title
        == "Baseline Reconnaissance & Attack Surface Discovery"
    )
    assert "LLM schema validation failed" in result.escalation_reason
