"""Create execution_contexts table for archived agent task working state.

Revision ID: 0008_execution_contexts
Revises: 0007_agent_memories
Create Date: 2026-08-27 10:55:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008_execution_contexts"
down_revision: str | None = "0007_agent_memories"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "execution_contexts",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("task_id", sa.String(length=64), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column(
            "agent_id", sa.String(length=64), sa.ForeignKey("ai_employees.id"), nullable=False
        ),
        sa.Column("role_id", sa.String(length=64), sa.ForeignKey("roles.id"), nullable=False),
        sa.Column(
            "engagement_id", sa.String(length=64), sa.ForeignKey("engagements.id"), nullable=False
        ),
        sa.Column(
            "department_id", sa.String(length=64), sa.ForeignKey("departments.id"), nullable=False
        ),
        sa.Column("final_status", sa.String(length=32), nullable=False),
        sa.Column("archive_payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(length=64), nullable=False),
        sa.Column("closed_at", sa.String(length=64), nullable=False),
    )
    op.create_index("idx_execution_contexts_id", "execution_contexts", ["id"])
    op.create_index("idx_execution_contexts_task_id", "execution_contexts", ["task_id"])
    op.create_index("idx_execution_contexts_agent_id", "execution_contexts", ["agent_id"])
    op.create_index("idx_execution_contexts_eng_id", "execution_contexts", ["engagement_id"])
    op.create_index("idx_execution_contexts_status", "execution_contexts", ["final_status"])


def downgrade() -> None:
    op.drop_table("execution_contexts")
