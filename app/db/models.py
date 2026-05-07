from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Interview(Base):
    __tablename__ = "interviews"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    company: Mapped[str]
    role: Mapped[str]
    round_types: Mapped[str]  # JSON-encoded list[str]
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(default="active")  # active | done | cancelled
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PrepPlan(Base):
    __tablename__ = "prep_plans"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    interview_id: Mapped[int] = mapped_column(ForeignKey("interviews.id"))
    plan_md: Mapped[str]
    time_budget_min: Mapped[int]
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    self_rating: Mapped[str | None] = mapped_column(nullable=True)  # easy | medium | hard
    skipped: Mapped[bool] = mapped_column(default=False)


class MockSession(Base):
    __tablename__ = "mock_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    interview_id: Mapped[int] = mapped_column(ForeignKey("interviews.id"))
    round_type: Mapped[str]
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    transcript_json: Mapped[str | None] = mapped_column(nullable=True)
    rubric_json: Mapped[str | None] = mapped_column(nullable=True)
    critique_json: Mapped[str | None] = mapped_column(nullable=True)


class WeakPattern(Base):
    __tablename__ = "weak_patterns"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    pattern: Mapped[str]
    weight: Mapped[float] = mapped_column(default=1.0)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_session_id: Mapped[int | None] = mapped_column(
        ForeignKey("mock_sessions.id"), nullable=True
    )


class WaWindowState(Base):
    __tablename__ = "wa_window_state"

    recipient_e164: Mapped[str] = mapped_column(primary_key=True)
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_template_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class OutboundIdempotency(Base):
    __tablename__ = "outbound_idempotency"

    idempotency_key: Mapped[str] = mapped_column(primary_key=True)
    message_sid: Mapped[str]
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
