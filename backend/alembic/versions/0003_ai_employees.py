"""Create ai_employees table.

Revision ID: 0003_ai_employees
Revises: 0002_departments_and_roles
Create Date: 2026-08-26 12:50:00.000000
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0003_ai_employees"
down_revision: Union[str, None] = "0002_departments_and_roles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_employees",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("role_id", sa.String(length=64), sa.ForeignKey("roles.id"), nullable=False),
        sa.Column(
            "department_id", sa.String(length=64), sa.ForeignKey("departments.id"), nullable=False
        ),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="IDLE"),
        sa.Column("current_task_id", sa.String(length=64), nullable=True),
        sa.Column("memory_ref", sa.String(length=256), nullable=True),
        sa.Column("workspace_path", sa.String(length=256), nullable=True),
        sa.Column("x_coord", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("y_coord", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("created_at", sa.String(length=64), nullable=False),
        sa.Column("updated_at", sa.String(length=64), nullable=False),
    )
    op.create_index("idx_ai_employees_id", "ai_employees", ["id"])
    op.create_index("idx_ai_employees_role_id", "ai_employees", ["role_id"])
    op.create_index("idx_ai_employees_dept_id", "ai_employees", ["department_id"])
    op.create_index("idx_ai_employees_status", "ai_employees", ["status"])


def downgrade() -> None:
    op.drop_table("ai_employees")
