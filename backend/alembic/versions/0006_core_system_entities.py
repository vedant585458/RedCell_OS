"""Create agent_messages, process_executions, approvals, and audit_events tables.

Revision ID: 0006_core_system_entities
Revises: 0005_findings_evidence_risk
Create Date: 2026-08-26 13:05:00.000000
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0006_core_system_entities"
down_revision: Union[str, None] = "0005_findings_evidence_risk"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create agent_messages table
    op.create_table(
        "agent_messages",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "engagement_id", sa.String(length=64), sa.ForeignKey("engagements.id"), nullable=False
        ),
        sa.Column(
            "sender_agent_id",
            sa.String(length=64),
            sa.ForeignKey("ai_employees.id"),
            nullable=False,
        ),
        sa.Column(
            "recipient_agent_id",
            sa.String(length=64),
            sa.ForeignKey("ai_employees.id"),
            nullable=True,
        ),
        sa.Column("task_id", sa.String(length=64), sa.ForeignKey("tasks.id"), nullable=True),
        sa.Column(
            "message_type", sa.String(length=32), nullable=False, server_default="STATUS_UPDATE"
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.String(length=64), nullable=False),
    )
    op.create_index("idx_agent_messages_id", "agent_messages", ["id"])
    op.create_index("idx_agent_messages_engagement_id", "agent_messages", ["engagement_id"])
    op.create_index("idx_agent_messages_sender", "agent_messages", ["sender_agent_id"])
    op.create_index("idx_agent_messages_recipient", "agent_messages", ["recipient_agent_id"])
    op.create_index("idx_agent_messages_task", "agent_messages", ["task_id"])

    # 2. Create process_executions table
    op.create_table(
        "process_executions",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "engagement_id", sa.String(length=64), sa.ForeignKey("engagements.id"), nullable=False
        ),
        sa.Column("task_id", sa.String(length=64), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column(
            "agent_id", sa.String(length=64), sa.ForeignKey("ai_employees.id"), nullable=False
        ),
        sa.Column("workspace_path", sa.String(length=256), nullable=False),
        sa.Column("pid", sa.Integer(), nullable=False),
        sa.Column("exit_code", sa.Integer(), nullable=False),
        sa.Column("stdout_artifact_path", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("stderr_artifact_path", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("duration_sec", sa.Float(), nullable=False),
        sa.Column("timed_out", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("raw_command", sa.Text(), nullable=False),
        sa.Column("sanitized_command", sa.Text(), nullable=False),
        sa.Column("target", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("tool_name", sa.String(length=64), nullable=False, server_default="cli"),
        sa.Column("started_at", sa.String(length=64), nullable=False),
        sa.Column("completed_at", sa.String(length=64), nullable=False),
    )
    op.create_index("idx_process_executions_id", "process_executions", ["id"])
    op.create_index("idx_process_executions_eng_id", "process_executions", ["engagement_id"])
    op.create_index("idx_process_executions_task_id", "process_executions", ["task_id"])
    op.create_index("idx_process_executions_agent_id", "process_executions", ["agent_id"])

    # 3. Create approvals table
    op.create_table(
        "approvals",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "engagement_id", sa.String(length=64), sa.ForeignKey("engagements.id"), nullable=False
        ),
        sa.Column("task_id", sa.String(length=64), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column(
            "agent_id", sa.String(length=64), sa.ForeignKey("ai_employees.id"), nullable=False
        ),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("target_uri", sa.String(length=256), nullable=False),
        sa.Column("risk_description", sa.Text(), nullable=False),
        sa.Column("proposed_command", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING"),
        sa.Column("operator_id", sa.String(length=64), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("requested_at", sa.String(length=64), nullable=False),
        sa.Column("decided_at", sa.String(length=64), nullable=True),
    )
    op.create_index("idx_approvals_id", "approvals", ["id"])
    op.create_index("idx_approvals_eng_id", "approvals", ["engagement_id"])
    op.create_index("idx_approvals_task_id", "approvals", ["task_id"])
    op.create_index("idx_approvals_status", "approvals", ["status"])

    # 4. Create audit_events table
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("seq", sa.Integer(), nullable=False, unique=True),
        sa.Column(
            "engagement_id", sa.String(length=64), sa.ForeignKey("engagements.id"), nullable=False
        ),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("actor_type", sa.String(length=32), nullable=False, server_default="AGENT"),
        sa.Column("actor_id", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("prev_event_hash", sa.String(length=64), nullable=False, server_default="0" * 64),
        sa.Column("event_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.String(length=64), nullable=False),
    )
    op.create_index("idx_audit_events_id", "audit_events", ["id"])
    op.create_index("idx_audit_events_seq", "audit_events", ["seq"])
    op.create_index("idx_audit_events_eng_id", "audit_events", ["engagement_id"])
    op.create_index("idx_audit_events_corr_id", "audit_events", ["correlation_id"])


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("approvals")
    op.drop_table("process_executions")
    op.drop_table("agent_messages")
