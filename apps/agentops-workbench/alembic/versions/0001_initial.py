"""initial schema: runs, tool_calls, actions.

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-09

"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("principal_id", sa.String(128), index=True),
        sa.Column("state", sa.String(32), index=True),
        sa.Column("graph_version", sa.String(32)),
        sa.Column("prompt_version", sa.String(32)),
        sa.Column("model_config", sa.JSON),
        sa.Column("budget", sa.JSON, default=dict),
        sa.Column("code_sha", sa.String(64)),
        sa.Column("trace_id", sa.String(64), nullable=True),
        sa.Column("task", sa.Text),
        sa.Column("answer", sa.Text, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("total_tokens", sa.Integer, default=0),
        sa.Column("cost_usd", sa.Float, default=0.0),
        sa.Column("created_at", sa.DateTime),
        sa.Column("updated_at", sa.DateTime),
    )
    op.create_table(
        "tool_calls",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("run_id", sa.String(64), sa.ForeignKey("runs.id"), index=True),
        sa.Column("tool_name", sa.String(64)),
        sa.Column("policy_decision", sa.String(32)),
        sa.Column("action_key", sa.String(128), index=True),
        sa.Column("args_canonical", sa.JSON, default=dict),
        sa.Column("outcome", sa.JSON, default=dict),
        sa.Column("latency_ms", sa.Integer, default=0),
        sa.Column("created_at", sa.DateTime),
    )
    op.create_table(
        "actions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("run_id", sa.String(64), sa.ForeignKey("runs.id"), index=True),
        sa.Column("tool_name", sa.String(64)),
        sa.Column("args_canonical", sa.JSON),
        sa.Column("nonce", sa.String(64), unique=True, index=True),
        sa.Column("expires_at", sa.DateTime),
        sa.Column("approved_by", sa.String(128), nullable=True),
        sa.Column("used_at", sa.DateTime, nullable=True),
        sa.Column("cancelled", sa.Boolean, default=False),
        sa.Column("created_at", sa.DateTime),
        sa.UniqueConstraint("nonce", name="uq_actions_nonce"),
    )


def downgrade() -> None:
    op.drop_table("actions")
    op.drop_table("tool_calls")
    op.drop_table("runs")
