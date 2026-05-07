"""app_config: add check constraints and fix updated_at server_default

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-05-07

"""
from alembic import op

revision = "c2d3e4f5a6b7"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE app_config
        ADD CONSTRAINT ck_app_config_key
            CHECK (key IN ('llm.primary_provider', 'llm.fast_provider'))
    """)
    op.execute("""
        ALTER TABLE app_config
        ADD CONSTRAINT ck_app_config_value
            CHECK (value IN ('anthropic', 'gemini'))
    """)
    # Fix updated_at to use server default so rows written outside ORM are correct.
    op.execute("""
        ALTER TABLE app_config
        ALTER COLUMN updated_at SET DEFAULT now()
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE app_config DROP CONSTRAINT ck_app_config_key")
    op.execute("ALTER TABLE app_config DROP CONSTRAINT ck_app_config_value")
    op.execute("ALTER TABLE app_config ALTER COLUMN updated_at DROP DEFAULT")
