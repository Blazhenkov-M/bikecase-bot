"""add_events_slots_bookings

Revision ID: c4e8f1a2b3d5
Revises: b23a97db9c46
Create Date: 2026-03-21 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c4e8f1a2b3d5"
down_revision: Union[str, None] = "b23a97db9c46"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

event_status = postgresql.ENUM(
    "draft", "published", "completed", "cancelled",
    name="event_status",
    create_type=False,
)
slot_type = postgresql.ENUM(
    "dropoff", "pickup",
    name="slot_type",
    create_type=False,
)
booking_status = postgresql.ENUM(
    "confirmed", "cancelled",
    name="booking_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()

    # username may change — drop uniqueness from init migration (if present)
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_username_key")
    op.execute("CREATE INDEX IF NOT EXISTS ix_users_username ON users (username)")

    # Create enums once; columns use create_type=False to avoid duplicates
    event_status.create(bind, checkfirst=True)
    slot_type.create(bind, checkfirst=True)
    booking_status.create(bind, checkfirst=True)

    op.create_table(
        "locations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("address", sa.String(length=512), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column("status", event_status, server_default="draft", nullable=False),
        sa.Column("booking_opens_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("booking_closes_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(now() AT TIME ZONE 'Europe/Moscow')"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(now() AT TIME ZONE 'Europe/Moscow')"),
            nullable=False,
        ),
        sa.CheckConstraint("booking_opens_at < booking_closes_at", name="ck_events_booking_window"),
        sa.CheckConstraint("starts_on <= ends_on", name="ck_events_date_range"),
        sa.CheckConstraint("price >= 0", name="ck_events_price_non_negative"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_events_status", "events", ["status"], unique=False)

    op.create_table(
        "event_slots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=False),
        sa.Column("slot_type", slot_type, nullable=False),
        sa.Column("service_date", sa.Date(), nullable=False),
        sa.Column("starts_at", sa.Time(), nullable=False),
        sa.Column("ends_at", sa.Time(), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.CheckConstraint("starts_at < ends_at", name="ck_event_slots_time_window"),
        sa.CheckConstraint("capacity > 0", name="ck_event_slots_capacity_positive"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_event_slots_event_id", "event_slots", ["event_id"], unique=False)
    op.create_index("ix_event_slots_location_id", "event_slots", ["location_id"], unique=False)
    op.create_index(
        "ix_event_slots_event_type_active",
        "event_slots",
        ["event_id", "slot_type", "is_active"],
        unique=False,
    )

    op.create_table(
        "bookings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_tg_id", sa.BigInteger(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("participant_first_name", sa.String(length=64), nullable=False),
        sa.Column("participant_last_name", sa.String(length=64), nullable=False),
        sa.Column("bicycle_brand", sa.String(length=128), nullable=False),
        sa.Column("bicycle_color", sa.String(length=64), nullable=False),
        sa.Column("dropoff_slot_id", sa.Integer(), nullable=False),
        sa.Column("pickup_slot_id", sa.Integer(), nullable=False),
        sa.Column("prestart_service", sa.Boolean(), nullable=False),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column("status", booking_status, server_default="confirmed", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(now() AT TIME ZONE 'Europe/Moscow')"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(now() AT TIME ZONE 'Europe/Moscow')"),
            nullable=False,
        ),
        sa.CheckConstraint("price >= 0", name="ck_bookings_price_non_negative"),
        sa.CheckConstraint("dropoff_slot_id <> pickup_slot_id", name="ck_bookings_distinct_slots"),
        sa.ForeignKeyConstraint(["user_tg_id"], ["users.tg_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["dropoff_slot_id"], ["event_slots.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["pickup_slot_id"], ["event_slots.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bookings_user_tg_id", "bookings", ["user_tg_id"], unique=False)
    op.create_index("ix_bookings_event_id", "bookings", ["event_id"], unique=False)
    op.create_index("ix_bookings_dropoff_slot_id", "bookings", ["dropoff_slot_id"], unique=False)
    op.create_index("ix_bookings_pickup_slot_id", "bookings", ["pickup_slot_id"], unique=False)
    op.create_index("ix_bookings_status", "bookings", ["status"], unique=False)
    op.create_index(
        "uq_bookings_user_event_active",
        "bookings",
        ["user_tg_id", "event_id"],
        unique=True,
        postgresql_where=sa.text("status = 'confirmed'"),
    )


def downgrade() -> None:
    op.drop_index("uq_bookings_user_event_active", table_name="bookings")
    op.drop_index("ix_bookings_status", table_name="bookings")
    op.drop_index("ix_bookings_pickup_slot_id", table_name="bookings")
    op.drop_index("ix_bookings_dropoff_slot_id", table_name="bookings")
    op.drop_index("ix_bookings_event_id", table_name="bookings")
    op.drop_index("ix_bookings_user_tg_id", table_name="bookings")
    op.drop_table("bookings")

    op.drop_index("ix_event_slots_event_type_active", table_name="event_slots")
    op.drop_index("ix_event_slots_location_id", table_name="event_slots")
    op.drop_index("ix_event_slots_event_id", table_name="event_slots")
    op.drop_table("event_slots")

    op.drop_index("ix_events_status", table_name="events")
    op.drop_table("events")
    op.drop_table("locations")

    bind = op.get_bind()
    booking_status.drop(bind, checkfirst=True)
    slot_type.drop(bind, checkfirst=True)
    event_status.drop(bind, checkfirst=True)

    op.execute("DROP INDEX IF EXISTS ix_users_username")
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT users_username_key UNIQUE (username)"
    )
