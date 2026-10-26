"""fix_timestamp_defaults

`now() AT TIME ZONE 'Europe/Moscow'` returns a naive Moscow wall time, which
timestamptz columns interpret in the session timezone (UTC) — values ended up
shifted by +3h. Use plain now() instead.

Revision ID: d7a1b9e4f2c6
Revises: c4e8f1a2b3d5
Create Date: 2026-10-24 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d7a1b9e4f2c6"
down_revision: Union[str, None] = "c4e8f1a2b3d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNS = (
    ("users", "reg_date"),
    ("events", "created_at"),
    ("events", "updated_at"),
    ("bookings", "created_at"),
    ("bookings", "updated_at"),
)
OLD_DEFAULT = "(now() AT TIME ZONE 'Europe/Moscow')"


def upgrade() -> None:
    for table, column in COLUMNS:
        op.alter_column(table, column, server_default=sa.text("now()"))


def downgrade() -> None:
    for table, column in COLUMNS:
        if (table, column) == ("users", "reg_date"):
            op.alter_column(table, column, server_default=sa.text("CURRENT_TIMESTAMP"))
        else:
            op.alter_column(table, column, server_default=sa.text(OLD_DEFAULT))
