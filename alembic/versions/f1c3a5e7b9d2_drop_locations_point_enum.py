"""drop_locations_point_enum

Пункт приёма в Москве теперь колонка event_slots.point (enum moscow_point;
имя `point` занято встроенным геометрическим типом Postgres), таблица locations
удалена. Даты мероприятия = окна выдачи/сдачи: starts_on/ends_on удалены,
issue_*/return_* стали NOT NULL.

Слоты на точках без code (старые тестовые) удаляются — их не на что отобразить.

Revision ID: f1c3a5e7b9d2
Revises: e5b2c7d9a1f3
Create Date: 2026-10-26 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f1c3a5e7b9d2"
down_revision: Union[str, None] = "e5b2c7d9a1f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

point = postgresql.ENUM(
    "krylatskoe", "zapovednaya", "starovatutinsky",
    name="moscow_point",
    create_type=False,
)

EVENT_WINDOW_COLUMNS = (
    "issue_date", "issue_starts_at", "issue_ends_at",
    "return_date", "return_starts_at", "return_ends_at",
)


def upgrade() -> None:
    bind = op.get_bind()
    point.create(bind, checkfirst=True)

    # --- event_slots: location_id -> point ---
    op.add_column("event_slots", sa.Column("point", point, nullable=True))
    op.execute(
        "UPDATE event_slots s SET point = l.code::moscow_point "
        "FROM locations l WHERE l.id = s.location_id AND l.code IS NOT NULL"
    )
    op.execute("DELETE FROM event_slots WHERE point IS NULL")
    op.alter_column("event_slots", "point", nullable=False)

    op.drop_index("ix_event_slots_event_type_active", table_name="event_slots")
    op.drop_index("ix_event_slots_event_id", table_name="event_slots")
    op.drop_column("event_slots", "location_id")  # вместе с FK и ix_event_slots_location_id
    op.create_unique_constraint(
        "uq_event_slots_event_type_point",
        "event_slots",
        ["event_id", "slot_type", "point"],
    )
    op.drop_table("locations")

    # --- events: даты мероприятия = окна выдачи/сдачи ---
    op.execute(
        "UPDATE events SET "
        "issue_date = COALESCE(issue_date, starts_on), "
        "issue_starts_at = COALESCE(issue_starts_at, '11:00'), "
        "issue_ends_at = COALESCE(issue_ends_at, '20:00'), "
        "return_date = COALESCE(return_date, ends_on), "
        "return_starts_at = COALESCE(return_starts_at, '11:00'), "
        "return_ends_at = COALESCE(return_ends_at, '20:00')"
    )
    for column in EVENT_WINDOW_COLUMNS:
        op.alter_column("events", column, nullable=False)

    op.drop_constraint("ck_events_date_range", "events", type_="check")
    op.drop_column("events", "starts_on")
    op.drop_column("events", "ends_on")
    op.create_check_constraint("ck_events_date_range", "events", "issue_date <= return_date")


def downgrade() -> None:
    # --- events ---
    op.drop_constraint("ck_events_date_range", "events", type_="check")
    op.add_column("events", sa.Column("starts_on", sa.Date(), nullable=True))
    op.add_column("events", sa.Column("ends_on", sa.Date(), nullable=True))
    op.execute("UPDATE events SET starts_on = issue_date, ends_on = return_date")
    op.alter_column("events", "starts_on", nullable=False)
    op.alter_column("events", "ends_on", nullable=False)
    op.create_check_constraint("ck_events_date_range", "events", "starts_on <= ends_on")
    for column in EVENT_WINDOW_COLUMNS:
        op.alter_column("events", column, nullable=True)

    # --- locations обратно, по строке на каждый пункт ---
    op.create_table(
        "locations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=32), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("address", sa.String(length=512), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_locations_code"),
    )
    op.execute(
        "INSERT INTO locations (code, name, address) VALUES "
        "('krylatskoe', 'Крылатское', 'Москва, Крылатское'), "
        "('zapovednaya', 'Заповедная', 'Москва, ул. Заповедная'), "
        "('starovatutinsky', 'Староватутинский', 'Москва, Староватутинский пр.')"
    )

    op.drop_constraint("uq_event_slots_event_type_point", "event_slots", type_="unique")
    op.add_column("event_slots", sa.Column("location_id", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE event_slots s SET location_id = l.id "
        "FROM locations l WHERE l.code = s.point::text"
    )
    op.alter_column("event_slots", "location_id", nullable=False)
    op.create_foreign_key(
        "event_slots_location_id_fkey",
        "event_slots",
        "locations",
        ["location_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_event_slots_location_id", "event_slots", ["location_id"], unique=False)
    op.create_index("ix_event_slots_event_id", "event_slots", ["event_id"], unique=False)
    op.create_index(
        "ix_event_slots_event_type_active",
        "event_slots",
        ["event_id", "slot_type", "is_active"],
        unique=False,
    )
    op.drop_column("event_slots", "point")
    point.drop(op.get_bind(), checkfirst=True)
