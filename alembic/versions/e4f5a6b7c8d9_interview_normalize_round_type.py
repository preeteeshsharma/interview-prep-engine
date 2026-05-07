"""interviews: normalize round_types (JSON array) → round_type (scalar)

One Interview row per (company, round_type). Existing rows with multi-round
JSON arrays are expanded into separate rows during upgrade.

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-05-07

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "e4f5a6b7c8d9"
down_revision = "d3e4f5a6b7c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add the new scalar column.
    op.add_column("interviews", sa.Column("round_type", sa.Text(), nullable=True))

    # Migrate existing rows: expand JSON arrays into separate rows.
    # Each existing row's first element becomes the in-place round_type;
    # additional elements get new rows cloned from the original.
    conn = op.get_bind()
    rows = conn.execute(text(
        "SELECT id, company, role, round_types, scheduled_for, status, created_at FROM interviews"
    )).fetchall()

    for row in rows:
        import json
        try:
            rounds = json.loads(row.round_types) if row.round_types else []
        except Exception:
            rounds = []

        first = rounds[0] if rounds else None
        conn.execute(
            text("UPDATE interviews SET round_type = :rt WHERE id = :id"),
            {"rt": first, "id": row.id},
        )
        for extra_round in rounds[1:]:
            conn.execute(
                text("""
                    INSERT INTO interviews (company, role, round_type, scheduled_for, status, created_at)
                    VALUES (:company, :role, :rt, :sf, :status, :created_at)
                """),
                {
                    "company": row.company,
                    "role": row.role,
                    "rt": extra_round,
                    "sf": row.scheduled_for,
                    "status": row.status,
                    "created_at": row.created_at,
                },
            )

    # Drop the old JSON column.
    op.drop_column("interviews", "round_types")


def downgrade() -> None:
    import json as _json
    op.add_column("interviews", sa.Column("round_types", sa.Text(), nullable=True))
    conn = op.get_bind()
    conn.execute(text(
        "UPDATE interviews SET round_types = json_array(round_type) WHERE round_type IS NOT NULL"
    ))
    conn.execute(text("UPDATE interviews SET round_types = '[]' WHERE round_type IS NULL"))
    op.drop_column("interviews", "round_type")
