"""Initial database schema for Engagements, Scope, ROE, and Event Store.

Revision ID: 0001_initial
Revises: None
Create Date: 2026-08-26 12:40:00.000000
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create engagements table
    op.create_table(
        "engagements",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("title", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="CREATED"),
        sa.Column("organization", sa.String(length=128), nullable=False),
        sa.Column("authorized_by", sa.String(length=128), nullable=False),
        sa.Column("operator_id", sa.String(length=64), nullable=False),
        sa.Column("valid_from_utc", sa.String(length=64), nullable=False),
        sa.Column("valid_until_utc", sa.String(length=64), nullable=False),
        sa.Column("timezone", sa.String(length=32), nullable=False, server_default="UTC"),
        sa.Column("emergency_freeze", sa.String(length=8), nullable=False, server_default="false"),
        sa.Column("target_scope_json", sa.Text(), nullable=False),
        sa.Column("rules_of_engagement_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(length=64), nullable=False),
        sa.Column("updated_at", sa.String(length=64), nullable=False),
    )
    op.create_index("idx_engagements_id", "engagements", ["id"])
    op.create_index("idx_engagements_status", "engagements", ["status"])

    # 2. Create stored_events table
    op.create_table(
        "stored_events",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("seq", sa.Integer(), nullable=False, unique=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("engagement_id", sa.String(length=64), nullable=True),
        sa.Column("agent_id", sa.String(length=64), nullable=True),
        sa.Column("department_id", sa.String(length=64), nullable=True),
        sa.Column("task_id", sa.String(length=64), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("timestamp_utc", sa.String(length=64), nullable=False),
    )
    op.create_index("idx_stored_events_seq", "stored_events", ["seq"])
    op.create_index("idx_stored_events_eng_seq", "stored_events", ["engagement_id", "seq"])
    op.create_index("idx_stored_events_corr", "stored_events", ["correlation_id"])


def downgrade() -> None:
    op.drop_table("stored_events")
    op.drop_table("engagements")
