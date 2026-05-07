"""schema cleanup: drop unused columns across all tables

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-05-07

"""
from alembic import op

revision = "f5a6b7c8d9e0"
down_revision = "e4f5a6b7c8d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # interviews: drop status + created_at (status never updated, created_at replaced by id ordering)
    op.drop_column("interviews", "status")
    op.drop_column("interviews", "created_at")

    # prep_plans: drop time_budget_min (hardcoded 120, never read back)
    op.drop_column("prep_plans", "time_budget_min")

    # weak_patterns: drop last_seen_at + source_session_id (written, never read)
    op.drop_column("weak_patterns", "last_seen_at")
    op.drop_column("weak_patterns", "source_session_id")

    # wa_window_state: drop last_template_at (record_template_sent never called)
    op.drop_column("wa_window_state", "last_template_at")

    # outbound_idempotency: drop message_sid + sent_at (written, never read)
    op.drop_column("outbound_idempotency", "message_sid")
    op.drop_column("outbound_idempotency", "sent_at")

    # app_config: drop updated_at (never read)
    op.drop_column("app_config", "updated_at")


def downgrade() -> None:
    import sqlalchemy as sa
    op.add_column("interviews", sa.Column("status", sa.Text(), nullable=True))
    op.add_column("interviews", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("prep_plans", sa.Column("time_budget_min", sa.Integer(), nullable=True))
    op.add_column("weak_patterns", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("weak_patterns", sa.Column("source_session_id", sa.Integer(), nullable=True))
    op.add_column("wa_window_state", sa.Column("last_template_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("outbound_idempotency", sa.Column("message_sid", sa.Text(), nullable=True))
    op.add_column("outbound_idempotency", sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("app_config", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
