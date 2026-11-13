"""krylatskoe: daily limits on events, chosen day on applications

Revision ID: 0002_krylatskoe_limits
Revises: 0001_init
Create Date: 2026-11-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_krylatskoe_limits"
down_revision: Union[str, None] = "0001_init"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # NULL у существующих строк: лимит не задан / день не выбран.
    op.add_column("events", sa.Column("krylatskoe_dropoff_limit", sa.Integer(), nullable=True))
    op.add_column("events", sa.Column("krylatskoe_pickup_limit", sa.Integer(), nullable=True))
    op.create_check_constraint("ck_events_krylatskoe_dropoff_limit", "events", "krylatskoe_dropoff_limit > 0")
    op.create_check_constraint("ck_events_krylatskoe_pickup_limit", "events", "krylatskoe_pickup_limit > 0")

    op.add_column("applications", sa.Column("dropoff_date", sa.Date(), nullable=True))
    op.add_column("applications", sa.Column("pickup_date", sa.Date(), nullable=True))
    op.create_check_constraint(
        "ck_applications_dropoff_date", "applications", "dropoff_date IS NULL OR dropoff_point = 'krylatskoe'"
    )
    op.create_check_constraint(
        "ck_applications_pickup_date", "applications", "pickup_date IS NULL OR pickup_point = 'krylatskoe'"
    )


def downgrade() -> None:
    op.drop_constraint("ck_applications_pickup_date", "applications", type_="check")
    op.drop_constraint("ck_applications_dropoff_date", "applications", type_="check")
    op.drop_column("applications", "pickup_date")
    op.drop_column("applications", "dropoff_date")
    op.drop_constraint("ck_events_krylatskoe_pickup_limit", "events", type_="check")
    op.drop_constraint("ck_events_krylatskoe_dropoff_limit", "events", type_="check")
    op.drop_column("events", "krylatskoe_pickup_limit")
    op.drop_column("events", "krylatskoe_dropoff_limit")
