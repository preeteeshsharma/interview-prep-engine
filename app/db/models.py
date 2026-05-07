from datetime import datetime, timezone
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, JSON, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Interview(Base):
    __tablename__ = "interviews"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'done', 'cancelled')", name="ck_interview_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    company: Mapped[str]
    role: Mapped[str]
    round_type: Mapped[str | None] = mapped_column(nullable=True)  # DSA/LLD/… or None for multi-round
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(default="active")  # active | done | cancelled
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PrepPlan(Base):
    __tablename__ = "prep_plans"
    __table_args__ = (
        CheckConstraint(
            "self_rating IN ('easy', 'medium', 'hard') OR self_rating IS NULL",
            name="ck_prepplan_self_rating",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    interview_id: Mapped[int] = mapped_column(ForeignKey("interviews.id"))
    vault_path: Mapped[str | None] = mapped_column(nullable=True)  # e.g. google/dsa/1778165199-plan.md
    drill_label: Mapped[str | None] = mapped_column(nullable=True)  # first ### heading, for weak_patterns
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
    pending_prep: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class AppConfig(Base):
    __tablename__ = "app_config"
    __table_args__ = (
        CheckConstraint(
            "key IN ('llm.primary_provider', 'llm.fast_provider')",
            name="ck_app_config_key",
        ),
        CheckConstraint(
            "value IN ('anthropic', 'gemini')",
            name="ck_app_config_value",
        ),
    )

    key: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[str]
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class OutboundIdempotency(Base):
    __tablename__ = "outbound_idempotency"

    idempotency_key: Mapped[str] = mapped_column(primary_key=True)
    message_sid: Mapped[str]
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(default="sent")  # sent | send_failed
