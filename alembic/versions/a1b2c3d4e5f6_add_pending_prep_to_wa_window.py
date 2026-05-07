"""add_pending_prep_to_wa_window

Revision ID: a1b2c3d4e5f6
Revises: 7167bbf92946
Create Date: 2026-05-07 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '7167bbf92946'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Column was added directly in Supabase; use IF NOT EXISTS to be idempotent.
    op.execute(
        "ALTER TABLE wa_window_state ADD COLUMN IF NOT EXISTS pending_prep JSON"
    )


def downgrade() -> None:
    op.drop_column('wa_window_state', 'pending_prep')
