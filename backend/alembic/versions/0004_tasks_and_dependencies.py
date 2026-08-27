"""Create tasks and task_dependencies tables.

Revision ID: 0004_tasks_and_dependencies
Revises: 0003_ai_employees
Create Date: 2026-08-26 12:55:00.000000
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0004_tasks_and_dependencies"
down_revision: Union[str, None] = "0003_ai_employees"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create tasks table
    op.create_table(
        "tasks",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("engagement_id", sa.String(length=64), sa.ForeignKey("engagements.id"), nullable=False),
        sa.Column("department_id", sa.String(length=64), sa.ForeignKey("departments.id"), nullable=False),
        sa.Column("title", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("assigned_role", sa.String(length=64), nullable=False),
        sa.Column("assigned_agent_id", sa.String(length=64), sa.ForeignKey("ai_employees.id"), nullable=True),
        sa.Column("parent_task_id", sa.String(length=64), sa.ForeignKey("tasks.id"), nullable=True),
        sa.Column("requires_approval_gate", sa.String(length=64), nullable=True),
        sa.Column("input_context_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("output_artifacts_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.String(length=64), nullable=False),
        sa.Column("updated_at", sa.String(length=64), nullable=False),
    )
    op.create_index("idx_tasks_id", "tasks", ["id"])
    op.create_index("idx_tasks_engagement_id", "tasks", ["engagement_id"])
    op.create_index("idx_tasks_department_id", "tasks", ["department_id"])
    op.create_index("idx_tasks_status", "tasks", ["status"])
    op.create_index("idx_tasks_assigned_agent_id", "tasks", ["assigned_agent_id"])
    op.create_index("idx_tasks_parent_task_id", "tasks", ["parent_task_id"])

    # 2. Create task_dependencies edge table
    op.create_table(
        "task_dependencies",
        sa.Column("task_id", sa.String(length=64), sa.ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("depends_on_task_id", sa.String(length=64), sa.ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True),
        sa.CheckConstraint("task_id != depends_on_task_id", name="check_prevent_self_dependency"),
    )
    op.create_index("idx_task_deps_lookup", "task_dependencies", ["task_id", "depends_on_task_id"])
    op.create_index("idx_task_deps_reverse", "task_dependencies", ["depends_on_task_id", "task_id"])


def downgrade() -> None:
    op.drop_table("task_dependencies")
    op.drop_table("tasks")
