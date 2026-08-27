"""Create agent_workspaces table.

Revision ID: 0009_agent_workspaces
Revises: 0008_execution_contexts
Create Date: 2026-08-27 11:05:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009_agent_workspaces"
down_revision: str | None = "0008_execution_contexts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_workspaces",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("task_id", sa.String(length=64), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column(
            "agent_id", sa.String(length=64), sa.ForeignKey("ai_employees.id"), nullable=False
        ),
        sa.Column(
            "engagement_id", sa.String(length=64), sa.ForeignKey("engagements.id"), nullable=False
        ),
        sa.Column("workspace_path", sa.String(length=512), nullable=False),
        sa.Column("tmp_path", sa.String(length=512), nullable=False),
        sa.Column("artifacts_path", sa.String(length=512), nullable=False),
        sa.Column("evidence_path", sa.String(length=512), nullable=False),
        sa.Column("permissions_mode", sa.String(length=16), nullable=False, server_default="0700"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="PROVISIONED"),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.String(length=64), nullable=False),
        sa.Column("updated_at", sa.String(length=64), nullable=False),
    )
    op.create_index("idx_agent_workspaces_id", "agent_workspaces", ["id"])
    op.create_index("idx_agent_workspaces_task_id", "agent_workspaces", ["task_id"])
    op.create_index("idx_agent_workspaces_agent_id", "agent_workspaces", ["agent_id"])
    op.create_index("idx_agent_workspaces_eng_id", "agent_workspaces", ["engagement_id"])
    op.create_index("idx_agent_workspaces_status", "agent_workspaces", ["status"])


def downgrade() -> None:
    op.drop_table("agent_workspaces")
