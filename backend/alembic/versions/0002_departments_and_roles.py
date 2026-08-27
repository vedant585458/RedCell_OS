"""Create departments and roles tables.

Revision ID: 0002_departments_and_roles
Revises: 0001_initial
Create Date: 2026-08-26 12:45:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_departments_and_roles"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Create departments table
    op.create_table(
        "departments",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "parent_org",
            sa.String(length=128),
            nullable=False,
            server_default="RedCell_OS Operations",
        ),
        sa.Column("color_theme", sa.String(length=32), nullable=False, server_default="blue"),
        sa.Column("created_at", sa.String(length=64), nullable=False),
    )
    op.create_index("idx_departments_id", "departments", ["id"])

    # 2. Create roles table
    op.create_table(
        "roles",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column(
            "department_id", sa.String(length=64), sa.ForeignKey("departments.id"), nullable=False
        ),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("version", sa.String(length=32), nullable=False, server_default="1.0.0"),
        sa.Column("system_prompt_template", sa.String(length=256), nullable=False),
        sa.Column("capabilities_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("allowed_tools_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("approval_gates_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("quotas_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.String(length=64), nullable=False),
    )
    op.create_index("idx_roles_id", "roles", ["id"])
    op.create_index("idx_roles_dept_id", "roles", ["department_id"])


def downgrade() -> None:
    op.drop_table("roles")
    op.drop_table("departments")
