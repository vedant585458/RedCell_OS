"""Create agent_memories persistent long-term memory table.

Revision ID: 0007_agent_memories
Revises: 0006_core_system_entities
Create Date: 2026-08-27 10:45:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007_agent_memories"
down_revision: str | None = "0006_core_system_entities"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_memories",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("role_id", sa.String(length=64), sa.ForeignKey("roles.id"), nullable=False),
        sa.Column("target_domain_or_org", sa.String(length=256), nullable=False),
        sa.Column(
            "engagement_id", sa.String(length=64), sa.ForeignKey("engagements.id"), nullable=True
        ),
        sa.Column(
            "memory_type", sa.String(length=64), nullable=False, server_default="TARGET_BEHAVIOR"
        ),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0.8"),
        sa.Column("source_task_id", sa.String(length=64), sa.ForeignKey("tasks.id"), nullable=True),
        sa.Column(
            "source_agent_id",
            sa.String(length=64),
            sa.ForeignKey("ai_employees.id"),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="PROPOSED"),
        sa.Column("approval_notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.String(length=64), nullable=False),
        sa.Column("updated_at", sa.String(length=64), nullable=False),
    )
    op.create_index("idx_agent_memories_id", "agent_memories", ["id"])
    op.create_index("idx_agent_memories_role_id", "agent_memories", ["role_id"])
    op.create_index("idx_agent_memories_target", "agent_memories", ["target_domain_or_org"])
    op.create_index("idx_agent_memories_engagement_id", "agent_memories", ["engagement_id"])
    op.create_index("idx_agent_memories_key", "agent_memories", ["key"])
    op.create_index("idx_agent_memories_status", "agent_memories", ["status"])


def downgrade() -> None:
    op.drop_table("agent_memories")
