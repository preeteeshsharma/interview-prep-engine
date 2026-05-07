from datetime import datetime
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, JSON, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Interview(Base):
    __tablename__ = "interviews"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    company: Mapped[str]
    role: Mapped[str]
    round_type: Mapped[str | None] = mapped_column(nullable=True)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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
    vault_path: Mapped[str | None] = mapped_column(nullable=True)
    drill_label: Mapped[str | None] = mapped_column(nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    self_rating: Mapped[str | None] = mapped_column(nullable=True)
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


class WaWindowState(Base):
    __tablename__ = "wa_window_state"

    recipient_e164: Mapped[str] = mapped_column(primary_key=True)
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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


class OutboundIdempotency(Base):
    __tablename__ = "outbound_idempotency"

    idempotency_key: Mapped[str] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(default="sent")
