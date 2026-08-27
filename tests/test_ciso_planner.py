"""Unit tests for CisoStrategicPlanner DAG generation, role/department validation, and anti-hallucination guardrails."""

import pytest
from app.ciso.intake_interpreter import InterpretedObjective
from app.ciso.planner import (
    CisoStrategicPlan,
    CisoStrategicPlanner,
    PlannedTask,
)
from app.domain.engagement import RulesOfEngagementSchema
from app.llm.mock_brain import MockAgentBrain
from app.llm.models import BrainResponse, BrainUsage


@pytest.mark.asyncio
async def test_ciso_strategic_planner_valid_dag_plan():
    valid_plan = CisoStrategicPlan(
        engagement_id="eng-mvp-001",
        mission_title="Staging Perimeter Security Assessment",
        departments_involved=["dept_recon", "dept_vulnerability", "dept_reporting"],
        tasks=[
            PlannedTask(
                task_id="TASK_01_RECON",
                title="Discover Web Attack Surface",
                department_id="dept_recon",
                assigned_role="role_web_discovery",
                priority=3,
                depends_on_task_ids=[],
            ),
            PlannedTask(
                task_id="TASK_02_VULN_SCAN",
                title="Assess Debug Configuration Exposure",
                department_id="dept_vulnerability",
                assigned_role="role_web_vuln_assessor",
                priority=3,
                depends_on_task_ids=["TASK_01_RECON"],
                requires_approval_gate="ACTIVE_EXPLOITATION_PROBE",
            ),
            PlannedTask(
                task_id="TASK_03_REPORT",
                title="Compile Final Penetration Test Report",
                department_id="dept_reporting",
                assigned_role="role_technical_writer",
                priority=2,
                depends_on_task_ids=["TASK_02_VULN_SCAN"],
            ),
        ],
        total_tasks=3,
        risk_assessment_summary="Standard web assessment workflow.",
    )

    mock_brain = MockAgentBrain(scripted_responses={CisoStrategicPlan: valid_plan})
    planner = CisoStrategicPlanner(brain=mock_brain)

    objectives = [
        InterpretedObjective(
            objective_id="OBJ-01",
            title="Discover endpoints",
            department_id="dept_recon",
            assigned_role="role_web_discovery",
            target_focus="Port 8088",
        )
    ]
    roe = RulesOfEngagementSchema()

    plan = await planner.generate_strategic_plan(
        engagement_id="eng-mvp-001",
        mission_title="Staging Assessment",
        objectives=objectives,
        rules_of_engagement=roe,
    )

    assert plan.engagement_id == "eng-mvp-001"
    assert plan.total_tasks == 3
    assert plan.registry_validation_passed is True
    assert len(plan.validation_errors) == 0
    assert plan.tasks[1].depends_on_task_ids == ["TASK_01_RECON"]
    assert plan.tasks[1].requires_approval_gate == "ACTIVE_EXPLOITATION_PROBE"


def test_plan_rejection_on_hallucinated_role_or_department():
    planner = CisoStrategicPlanner(brain=MockAgentBrain())
    hierarchy = planner.get_canonical_hierarchy_map()

    # Plan with hallucinated role and unknown department
    invalid_plan = CisoStrategicPlan(
        engagement_id="eng-invalid-01",
        mission_title="Hallucinated Mission",
        tasks=[
            PlannedTask(
                task_id="TASK_BAD_01",
                title="Quantum exploit scan",
                department_id="dept_unknown_dept",  # Unknown department!
                assigned_role="role_quantum_wizard",  # Unknown role!
                depends_on_task_ids=[],
            ),
            PlannedTask(
                task_id="TASK_BAD_02",
                title="Mismatched role department",
                department_id="dept_recon",
                assigned_role="role_technical_writer",  # Role belongs to dept_reporting, not dept_recon!
                depends_on_task_ids=["TASK_NON_EXISTENT"],  # Non-existent prerequisite!
            ),
        ],
    )

    validated = planner.validate_plan_against_registry(invalid_plan, hierarchy)
    assert validated.registry_validation_passed is False
    assert len(validated.validation_errors) >= 3
    assert any(
        "unknown department 'dept_unknown_dept'" in err
        for err in validated.validation_errors
    )
    assert any(
        "unknown role 'role_quantum_wizard'" in err
        for err in validated.validation_errors
    )
    assert any(
        "does not belong to department" in err for err in validated.validation_errors
    )
    assert any(
        "non-existent prerequisite" in err for err in validated.validation_errors
    )


def test_plan_rejection_on_self_dependency():
    planner = CisoStrategicPlanner(brain=MockAgentBrain())
    hierarchy = planner.get_canonical_hierarchy_map()

    self_dep_plan = CisoStrategicPlan(
        engagement_id="eng-self-dep",
        mission_title="Self Dep",
        tasks=[
            PlannedTask(
                task_id="TASK_01",
                title="Looping Task",
                department_id="dept_recon",
                assigned_role="role_web_discovery",
                depends_on_task_ids=["TASK_01"],  # Illegal self-dependency!
            )
        ],
    )

    validated = planner.validate_plan_against_registry(self_dep_plan, hierarchy)
    assert validated.registry_validation_passed is False
    assert any("illegal self-dependency" in err for err in validated.validation_errors)


@pytest.mark.asyncio
async def test_planner_fallback_on_llm_failure():
    class FailingBrain(MockAgentBrain):
        async def generate(self, *args, **kwargs) -> BrainResponse:
            return BrainResponse(
                content="Invalid response",
                usage=BrainUsage(total_tokens=5),
                model="mock",
            )

    planner = CisoStrategicPlanner(brain=FailingBrain())
    plan = await planner.generate_strategic_plan(
        engagement_id="eng-fallback-01",
        mission_title="Fallback Mission",
        objectives=[],
        rules_of_engagement=RulesOfEngagementSchema(),
        max_retries=1,
    )

    # Returns safe 3-task baseline plan
    assert plan.engagement_id == "eng-fallback-01"
    assert plan.total_tasks == 3
    assert plan.tasks[0].task_id == "TASK_01_RECON"
    assert plan.tasks[1].task_id == "TASK_02_VULN_SCAN"
    assert plan.tasks[2].task_id == "TASK_03_REPORT"
    assert "Fallback triggered" in plan.validation_errors[0]
