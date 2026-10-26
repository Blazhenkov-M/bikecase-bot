"""event_issue_return_location_code

Окна выдачи/сдачи велосипедов на мероприятии и постоянный код пункта приёма.

Revision ID: e5b2c7d9a1f3
Revises: d7a1b9e4f2c6
Create Date: 2026-10-26 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e5b2c7d9a1f3"
down_revision: Union[str, None] = "d7a1b9e4f2c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("locations", sa.Column("code", sa.String(length=32), nullable=True))
    op.create_unique_constraint("uq_locations_code", "locations", ["code"])

    op.add_column("events", sa.Column("issue_date", sa.Date(), nullable=True))
    op.add_column("events", sa.Column("issue_starts_at", sa.Time(), nullable=True))
    op.add_column("events", sa.Column("issue_ends_at", sa.Time(), nullable=True))
    op.add_column("events", sa.Column("return_date", sa.Date(), nullable=True))
    op.add_column("events", sa.Column("return_starts_at", sa.Time(), nullable=True))
    op.add_column("events", sa.Column("return_ends_at", sa.Time(), nullable=True))
    op.create_check_constraint(
        "ck_events_issue_window", "events", "issue_starts_at < issue_ends_at"
    )
    op.create_check_constraint(
        "ck_events_return_window", "events", "return_starts_at < return_ends_at"
    )


def downgrade() -> None:
    op.drop_constraint("ck_events_return_window", "events", type_="check")
    op.drop_constraint("ck_events_issue_window", "events", type_="check")
    op.drop_column("events", "return_ends_at")
    op.drop_column("events", "return_starts_at")
    op.drop_column("events", "return_date")
    op.drop_column("events", "issue_ends_at")
    op.drop_column("events", "issue_starts_at")
    op.drop_column("events", "issue_date")

    op.drop_constraint("uq_locations_code", "locations", type_="unique")
    op.drop_column("locations", "code")
