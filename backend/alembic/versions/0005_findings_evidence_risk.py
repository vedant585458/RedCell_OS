"""Create findings, evidence_records, and risk_scores tables.

Revision ID: 0005_findings_evidence_risk
Revises: 0004_tasks_and_dependencies
Create Date: 2026-08-26 13:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_findings_evidence_risk"
down_revision: str | None = "0004_tasks_and_dependencies"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Create findings table
    op.create_table(
        "findings",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "engagement_id", sa.String(length=64), sa.ForeignKey("engagements.id"), nullable=False
        ),
        sa.Column("task_id", sa.String(length=64), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column(
            "agent_id", sa.String(length=64), sa.ForeignKey("ai_employees.id"), nullable=False
        ),
        sa.Column("title", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("severity", sa.String(length=32), nullable=False, server_default="HIGH"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="DRAFT"),
        sa.Column("cwe_id", sa.String(length=64), nullable=False, server_default="CWE-200"),
        sa.Column("cve_id", sa.String(length=64), nullable=True),
        sa.Column("target_endpoint", sa.String(length=256), nullable=False),
        sa.Column("remediation_guidance", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.String(length=64), nullable=False),
        sa.Column("updated_at", sa.String(length=64), nullable=False),
    )
    op.create_index("idx_findings_id", "findings", ["id"])
    op.create_index("idx_findings_engagement_id", "findings", ["engagement_id"])
    op.create_index("idx_findings_task_id", "findings", ["task_id"])
    op.create_index("idx_findings_agent_id", "findings", ["agent_id"])
    op.create_index("idx_findings_severity", "findings", ["severity"])
    op.create_index("idx_findings_status", "findings", ["status"])

    # 2. Create evidence_records table
    op.create_table(
        "evidence_records",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "finding_id",
            sa.String(length=64),
            sa.ForeignKey("findings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "evidence_type", sa.String(length=32), nullable=False, server_default="RAW_OUTPUT"
        ),
        sa.Column("artifact_path", sa.String(length=512), nullable=False),
        sa.Column("sha256_hash", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.String(length=64), nullable=False),
    )
    op.create_index("idx_evidence_id", "evidence_records", ["id"])
    op.create_index("idx_evidence_finding_id", "evidence_records", ["finding_id"])

    # 3. Create risk_scores table
    op.create_table(
        "risk_scores",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "finding_id",
            sa.String(length=64),
            sa.ForeignKey("findings.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("cvss_v31_base_score", sa.Float(), nullable=False),
        sa.Column("cvss_vector", sa.String(length=128), nullable=False),
        sa.Column("attack_vector", sa.String(length=32), nullable=False, server_default="NETWORK"),
        sa.Column("attack_complexity", sa.String(length=32), nullable=False, server_default="LOW"),
        sa.Column(
            "privileges_required", sa.String(length=32), nullable=False, server_default="NONE"
        ),
        sa.Column("user_interaction", sa.String(length=32), nullable=False, server_default="NONE"),
        sa.Column("scope", sa.String(length=32), nullable=False, server_default="UNCHANGED"),
        sa.Column(
            "confidentiality_impact", sa.String(length=32), nullable=False, server_default="HIGH"
        ),
        sa.Column("integrity_impact", sa.String(length=32), nullable=False, server_default="NONE"),
        sa.Column(
            "availability_impact", sa.String(length=32), nullable=False, server_default="NONE"
        ),
        sa.Column("created_at", sa.String(length=64), nullable=False),
    )
    op.create_index("idx_risk_scores_id", "risk_scores", ["id"])
    op.create_index("idx_risk_scores_finding_id", "risk_scores", ["finding_id"])


def downgrade() -> None:
    op.drop_table("risk_scores")
    op.drop_table("evidence_records")
    op.drop_table("findings")
