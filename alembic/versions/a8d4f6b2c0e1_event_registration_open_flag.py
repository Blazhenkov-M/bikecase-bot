"""event_registration_open_flag

Регистрацию открывает/закрывает админ флагом registration_open вместо окна
booking_opens_at/booking_closes_at. Открытыми остаются published-события,
у которых окно ещё не закончилось.

Revision ID: a8d4f6b2c0e1
Revises: f1c3a5e7b9d2
Create Date: 2026-10-26 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a8d4f6b2c0e1"
down_revision: Union[str, None] = "f1c3a5e7b9d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("registration_open", sa.Boolean(), server_default="false", nullable=False),
    )
    op.execute(
        "UPDATE events SET registration_open = true "
        "WHERE status = 'published' AND now() BETWEEN booking_opens_at AND booking_closes_at"
    )
    op.drop_constraint("ck_events_booking_window", "events", type_="check")
    op.drop_column("events", "booking_opens_at")
    op.drop_column("events", "booking_closes_at")


def downgrade() -> None:
    op.add_column("events", sa.Column("booking_opens_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("events", sa.Column("booking_closes_at", sa.DateTime(timezone=True), nullable=True))
    # Открытые — до начала дня выдачи по Москве, закрытые — окно уже в прошлом.
    op.execute(
        "UPDATE events SET booking_opens_at = created_at, booking_closes_at = CASE "
        "WHEN registration_open THEN GREATEST("
        "created_at + interval '1 minute', issue_date::timestamp AT TIME ZONE 'Europe/Moscow') "
        "ELSE created_at + interval '1 minute' END"
    )
    op.alter_column("events", "booking_opens_at", nullable=False)
    op.alter_column("events", "booking_closes_at", nullable=False)
    op.create_check_constraint(
        "ck_events_booking_window", "events", "booking_opens_at < booking_closes_at"
    )
    op.drop_column("events", "registration_open")
