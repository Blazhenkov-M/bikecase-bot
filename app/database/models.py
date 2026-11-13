from __future__ import annotations

import enum
from datetime import date, datetime
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
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.database import Base


class EventStatus(str, enum.Enum):
    active = "active"
    registration_closed = "registration_closed"
    finished = "finished"


class Point(str, enum.Enum):
    """Точка приёма/выдачи велосипедов в Москве. Название, адрес и группа — в app/services/points.py."""

    zapovednaya = "zapovednaya"
    starovatutinsky = "starovatutinsky"
    krylatskoe = "krylatskoe"


class ApplicationStatus(str, enum.Enum):
    active = "active"
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
    # Согласие на обработку ПДн: NULL — не давал, иначе момент согласия.
    pd_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    applications: Mapped[list[Application]] = relationship(back_populates="user")

    def __repr__(self) -> str:
        return f"<User tg_id={self.tg_id} username={self.username}>"


class Event(Base):
    """Даты — диапазоны «с–по» включительно. workshop_* — общие для Заповедной и Староватутинского."""

    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint("price >= 0", name="ck_events_price_non_negative"),
        CheckConstraint("workshop_dropoff_from <= workshop_dropoff_to", name="ck_events_workshop_dropoff"),
        CheckConstraint("krylatskoe_dropoff_from <= krylatskoe_dropoff_to", name="ck_events_krylatskoe_dropoff"),
        CheckConstraint("workshop_pickup_from <= workshop_pickup_to", name="ck_events_workshop_pickup"),
        CheckConstraint("krylatskoe_pickup_from <= krylatskoe_pickup_to", name="ck_events_krylatskoe_pickup"),
        CheckConstraint("krylatskoe_dropoff_limit > 0", name="ck_events_krylatskoe_dropoff_limit"),
        CheckConstraint("krylatskoe_pickup_limit > 0", name="ck_events_krylatskoe_pickup_limit"),
        # Незавершённое событие может быть только одно.
        Index(
            "uq_events_single_current",
            text("(true)"),
            unique=True,
            postgresql_where=text("status <> 'finished'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[EventStatus] = mapped_column(
        Enum(EventStatus, name="event_status", native_enum=True),
        nullable=False,
        default=EventStatus.active,
        server_default=EventStatus.active.value,
        index=True,
    )
    workshop_dropoff_from: Mapped[date] = mapped_column(Date, nullable=False)
    workshop_dropoff_to: Mapped[date] = mapped_column(Date, nullable=False)
    krylatskoe_dropoff_from: Mapped[date] = mapped_column(Date, nullable=False)
    krylatskoe_dropoff_to: Mapped[date] = mapped_column(Date, nullable=False)
    workshop_pickup_from: Mapped[date] = mapped_column(Date, nullable=False)
    workshop_pickup_to: Mapped[date] = mapped_column(Date, nullable=False)
    krylatskoe_pickup_from: Mapped[date] = mapped_column(Date, nullable=False)
    krylatskoe_pickup_to: Mapped[date] = mapped_column(Date, nullable=False)
    # Мест в машине на один день в Крылатском. NULL — лимит не задан (события, созданные до его появления).
    krylatskoe_dropoff_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    krylatskoe_pickup_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
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

    applications: Mapped[list[Application]] = relationship(back_populates="event")

    def __repr__(self) -> str:
        return f"<Event id={self.id} name={self.name!r} status={self.status}>"


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (
        # Одна активная заявка клиента на событие; отменённые не мешают подать новую.
        Index(
            "uq_applications_user_event_active",
            "user_tg_id",
            "event_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index("ix_applications_event_id", "event_id"),
        # Конкретный день выбирается только для Крылатского.
        CheckConstraint(
            "dropoff_date IS NULL OR dropoff_point = 'krylatskoe'", name="ck_applications_dropoff_date"
        ),
        CheckConstraint(
            "pickup_date IS NULL OR pickup_point = 'krylatskoe'", name="ck_applications_pickup_date"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id", ondelete="RESTRICT"),
        nullable=False,
    )
    user_tg_id: Mapped[int] = mapped_column(
        ForeignKey("users.tg_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    first_name: Mapped[str] = mapped_column(String(64), nullable=False)
    last_name: Mapped[str] = mapped_column(String(64), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    bicycle_brand: Mapped[str] = mapped_column(String(128), nullable=False)
    bicycle_color: Mapped[str] = mapped_column(String(64), nullable=False)
    dropoff_point: Mapped[Point] = mapped_column(
        Enum(Point, name="moscow_point", native_enum=True),
        nullable=False,
    )
    pickup_point: Mapped[Point] = mapped_column(
        Enum(Point, name="moscow_point", native_enum=True),
        nullable=False,
    )
    # День сдачи/получения в Крылатском; для мастерских NULL — любой день диапазона.
    dropoff_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    pickup_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[ApplicationStatus] = mapped_column(
        Enum(ApplicationStatus, name="application_status", native_enum=True),
        nullable=False,
        default=ApplicationStatus.active,
        server_default=ApplicationStatus.active.value,
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

    user: Mapped[User] = relationship(back_populates="applications")
    event: Mapped[Event] = relationship(back_populates="applications")

    def __repr__(self) -> str:
        return f"<Application id={self.id} user={self.user_tg_id} event={self.event_id} status={self.status}>"
