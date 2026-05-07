"""prep_plans: replace plan_md with vault_path + drill_label

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-05-07

"""
from alembic import op
import sqlalchemy as sa

revision = "d3e4f5a6b7c8"
down_revision = "c2d3e4f5a6b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("prep_plans", sa.Column("vault_path", sa.Text(), nullable=True))
    op.add_column("prep_plans", sa.Column("drill_label", sa.Text(), nullable=True))
    op.drop_column("prep_plans", "plan_md")


def downgrade() -> None:
    op.add_column("prep_plans", sa.Column("plan_md", sa.Text(), nullable=False, server_default=""))
    op.drop_column("prep_plans", "drill_label")
    op.drop_column("prep_plans", "vault_path")
