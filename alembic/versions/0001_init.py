"""init: users, events, applications

Revision ID: 0001_init
Revises:
Create Date: 2026-10-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0001_init"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Типы создаются и удаляются явно: moscow_point используется в двух колонках,
# и create_table попытался бы создать его дважды.
# Не «point» — это встроенный геометрический тип Postgres.
event_status = postgresql.ENUM("active", "registration_closed", "finished", name="event_status", create_type=False)
point = postgresql.ENUM("zapovednaya", "starovatutinsky", "krylatskoe", name="moscow_point", create_type=False)
application_status = postgresql.ENUM("active", "cancelled", name="application_status", create_type=False)


def upgrade() -> None:
    op.execute("CREATE TYPE event_status AS ENUM ('active', 'registration_closed', 'finished')")
    op.execute("CREATE TYPE moscow_point AS ENUM ('zapovednaya', 'starovatutinsky', 'krylatskoe')")
    op.execute("CREATE TYPE application_status AS ENUM ('active', 'cancelled')")

    op.create_table(
        "users",
        sa.Column("tg_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=32), nullable=True),
        sa.Column("first_name", sa.String(length=64), nullable=True),
        sa.Column("last_name", sa.String(length=64), nullable=True),
        sa.Column("language_code", sa.String(length=10), nullable=True),
        sa.Column("is_premium", sa.Boolean(), nullable=True),
        sa.Column("reg_date", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("pd_consent_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("tg_id"),
    )
    op.create_index("ix_users_username", "users", ["username"])

    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column("status", event_status, server_default="active", nullable=False),
        sa.Column("workshop_dropoff_from", sa.Date(), nullable=False),
        sa.Column("workshop_dropoff_to", sa.Date(), nullable=False),
        sa.Column("krylatskoe_dropoff_from", sa.Date(), nullable=False),
        sa.Column("krylatskoe_dropoff_to", sa.Date(), nullable=False),
        sa.Column("workshop_pickup_from", sa.Date(), nullable=False),
        sa.Column("workshop_pickup_to", sa.Date(), nullable=False),
        sa.Column("krylatskoe_pickup_from", sa.Date(), nullable=False),
        sa.Column("krylatskoe_pickup_to", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("price >= 0", name="ck_events_price_non_negative"),
        sa.CheckConstraint("workshop_dropoff_from <= workshop_dropoff_to", name="ck_events_workshop_dropoff"),
        sa.CheckConstraint("krylatskoe_dropoff_from <= krylatskoe_dropoff_to", name="ck_events_krylatskoe_dropoff"),
        sa.CheckConstraint("workshop_pickup_from <= workshop_pickup_to", name="ck_events_workshop_pickup"),
        sa.CheckConstraint("krylatskoe_pickup_from <= krylatskoe_pickup_to", name="ck_events_krylatskoe_pickup"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_events_status", "events", ["status"])
    op.create_index(
        "uq_events_single_current",
        "events",
        [sa.text("(true)")],
        unique=True,
        postgresql_where=sa.text("status <> 'finished'"),
    )

    op.create_table(
        "applications",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("user_tg_id", sa.BigInteger(), nullable=False),
        sa.Column("first_name", sa.String(length=64), nullable=False),
        sa.Column("last_name", sa.String(length=64), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=False),
        sa.Column("bicycle_brand", sa.String(length=128), nullable=False),
        sa.Column("bicycle_color", sa.String(length=64), nullable=False),
        sa.Column("dropoff_point", point, nullable=False),
        sa.Column("pickup_point", point, nullable=False),
        sa.Column("status", application_status, server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_tg_id"], ["users.tg_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_applications_event_id", "applications", ["event_id"])
    op.create_index("ix_applications_user_tg_id", "applications", ["user_tg_id"])
    op.create_index("ix_applications_status", "applications", ["status"])
    op.create_index(
        "uq_applications_user_event_active",
        "applications",
        ["user_tg_id", "event_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_table("applications")
    op.drop_table("events")
    op.drop_table("users")
    op.execute("DROP TYPE application_status")
    op.execute("DROP TYPE moscow_point")
    op.execute("DROP TYPE event_status")
