from __future__ import annotations

import enum
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.database import Base


class EventStatus(str, enum.Enum):
    draft = "draft"
    published = "published"
    completed = "completed"
    cancelled = "cancelled"


class SlotType(str, enum.Enum):
    dropoff = "dropoff"
    pickup = "pickup"


class Point(str, enum.Enum):
    """Пункт приёма/возврата велосипедов в Москве. Название и адрес — в app/services/points.py."""

    krylatskoe = "krylatskoe"
    zapovednaya = "zapovednaya"
    starovatutinsky = "starovatutinsky"


class BookingStatus(str, enum.Enum):
    confirmed = "confirmed"
    cancelled = "cancelled"


class User(Base):
    __tablename__ = "users"

    tg_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    first_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    language_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    is_premium: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    reg_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    bookings: Mapped[list[Booking]] = relationship(back_populates="user")

    def __repr__(self) -> str:
        return f"<User tg_id={self.tg_id} username={self.username}>"


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint("issue_date <= return_date", name="ck_events_date_range"),
        CheckConstraint("price >= 0", name="ck_events_price_non_negative"),
        CheckConstraint("issue_starts_at < issue_ends_at", name="ck_events_issue_window"),
        CheckConstraint("return_starts_at < return_ends_at", name="ck_events_return_window"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[EventStatus] = mapped_column(
        Enum(EventStatus, name="event_status", native_enum=True),
        nullable=False,
        default=EventStatus.draft,
        server_default=EventStatus.draft.value,
        index=True,
    )
    # Регистрацию открывает/закрывает админ вручную.
    registration_open: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    # Выдача и сдача велосипедов на самом мероприятии (одно окно на всех).
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    issue_starts_at: Mapped[time] = mapped_column(Time, nullable=False)
    issue_ends_at: Mapped[time] = mapped_column(Time, nullable=False)
    return_date: Mapped[date] = mapped_column(Date, nullable=False)
    return_starts_at: Mapped[time] = mapped_column(Time, nullable=False)
    return_ends_at: Mapped[time] = mapped_column(Time, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    slots: Mapped[list[EventSlot]] = relationship(
        back_populates="event",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    bookings: Mapped[list[Booking]] = relationship(back_populates="event")

    def __repr__(self) -> str:
        return f"<Event id={self.id} name={self.name!r} status={self.status}>"


class EventSlot(Base):
    __tablename__ = "event_slots"
    __table_args__ = (
        CheckConstraint("starts_at < ends_at", name="ck_event_slots_time_window"),
        CheckConstraint("capacity > 0", name="ck_event_slots_capacity_positive"),
        # Одно окно на пункт и тип; индекс заодно покрывает выборку по event_id.
        UniqueConstraint("event_id", "slot_type", "point", name="uq_event_slots_event_type_point"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
    )
    point: Mapped[Point] = mapped_column(
        Enum(Point, name="moscow_point", native_enum=True),
        nullable=False,
    )
    slot_type: Mapped[SlotType] = mapped_column(
        Enum(SlotType, name="slot_type", native_enum=True),
        nullable=False,
    )
    service_date: Mapped[date] = mapped_column(Date, nullable=False)
    starts_at: Mapped[time] = mapped_column(Time, nullable=False)
    ends_at: Mapped[time] = mapped_column(Time, nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    event: Mapped[Event] = relationship(back_populates="slots")
    dropoff_bookings: Mapped[list[Booking]] = relationship(
        back_populates="dropoff_slot",
        foreign_keys="Booking.dropoff_slot_id",
    )
    pickup_bookings: Mapped[list[Booking]] = relationship(
        back_populates="pickup_slot",
        foreign_keys="Booking.pickup_slot_id",
    )

    def __repr__(self) -> str:
        return (
            f"<EventSlot id={self.id} event_id={self.event_id} "
            f"type={self.slot_type} point={self.point} date={self.service_date}>"
        )


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        CheckConstraint("price >= 0", name="ck_bookings_price_non_negative"),
        CheckConstraint("dropoff_slot_id <> pickup_slot_id", name="ck_bookings_distinct_slots"),
        Index(
            "uq_bookings_user_event_active",
            "user_tg_id",
            "event_id",
            unique=True,
            postgresql_where=text("status = 'confirmed'"),
        ),
        Index("ix_bookings_event_id", "event_id"),
        Index("ix_bookings_dropoff_slot_id", "dropoff_slot_id"),
        Index("ix_bookings_pickup_slot_id", "pickup_slot_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_tg_id: Mapped[int] = mapped_column(
        ForeignKey("users.tg_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id", ondelete="RESTRICT"),
        nullable=False,
    )
    participant_first_name: Mapped[str] = mapped_column(String(64), nullable=False)
    participant_last_name: Mapped[str] = mapped_column(String(64), nullable=False)
    bicycle_brand: Mapped[str] = mapped_column(String(128), nullable=False)
    bicycle_color: Mapped[str] = mapped_column(String(64), nullable=False)
    dropoff_slot_id: Mapped[int] = mapped_column(
        ForeignKey("event_slots.id", ondelete="RESTRICT"),
        nullable=False,
    )
    pickup_slot_id: Mapped[int] = mapped_column(
        ForeignKey("event_slots.id", ondelete="RESTRICT"),
        nullable=False,
    )
    prestart_service: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[BookingStatus] = mapped_column(
        Enum(BookingStatus, name="booking_status", native_enum=True),
        nullable=False,
        default=BookingStatus.confirmed,
        server_default=BookingStatus.confirmed.value,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user: Mapped[User] = relationship(back_populates="bookings")
    event: Mapped[Event] = relationship(back_populates="bookings")
    dropoff_slot: Mapped[EventSlot] = relationship(
        back_populates="dropoff_bookings",
        foreign_keys=[dropoff_slot_id],
    )
    pickup_slot: Mapped[EventSlot] = relationship(
        back_populates="pickup_bookings",
        foreign_keys=[pickup_slot_id],
    )

    def __repr__(self) -> str:
        return f"<Booking id={self.id} user={self.user_tg_id} event={self.event_id} status={self.status}>"
