"""SQLAlchemy models for runs, tool_calls, actions, experiments.

SQLite is used in MVP / CI; Postgres is the production target. The schema
is intentionally portable (no Postgres-only features used).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    principal_id: Mapped[str] = mapped_column(String(128), index=True)
    state: Mapped[str] = mapped_column(String(32), index=True)
    graph_version: Mapped[str] = mapped_column(String(32))
    prompt_version: Mapped[str] = mapped_column(String(32))
    model_config: Mapped[dict] = mapped_column(JSON)
    budget: Mapped[dict] = mapped_column(JSON, default=dict)
    code_sha: Mapped[str] = mapped_column(String(64))
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    task: Mapped[str] = mapped_column(Text)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    tool_calls: Mapped[list[ToolCall]] = relationship(back_populates="run", cascade="all, delete-orphan")
    actions: Mapped[list[Action]] = relationship(back_populates="run", cascade="all, delete-orphan")


class ToolCall(Base):
    __tablename__ = "tool_calls"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    tool_name: Mapped[str] = mapped_column(String(64))
    policy_decision: Mapped[str] = mapped_column(String(32))
    action_key: Mapped[str] = mapped_column(String(128), index=True)
    args_canonical: Mapped[dict] = mapped_column(JSON, default=dict)
    outcome: Mapped[dict] = mapped_column(JSON, default=dict)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    run: Mapped[Run] = relationship(back_populates="tool_calls")


class Action(Base):
    __tablename__ = "actions"
    __table_args__ = (UniqueConstraint("nonce", name="uq_actions_nonce"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    tool_name: Mapped[str] = mapped_column(String(64))
    args_canonical: Mapped[dict] = mapped_column(JSON)
    nonce: Mapped[str] = mapped_column(String(64), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    approved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancelled: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    run: Mapped[Run] = relationship(back_populates="actions")
