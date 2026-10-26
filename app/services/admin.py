from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from html import escape

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import Booking, BookingStatus, Event, EventSlot, EventStatus, Point, SlotType
from app.services.points import POINTS


MOSCOW = timezone(timedelta(hours=3))
SLOT_CAPACITY = 20
# При создании задаются только даты; время меняется потом в редактировании события.
DEFAULT_STARTS_AT = time(11, 0)
DEFAULT_ENDS_AT = time(20, 0)


@dataclass(frozen=True, slots=True)
class Window:
    day: date
    starts_at: time = DEFAULT_STARTS_AT
    ends_at: time = DEFAULT_ENDS_AT

    def label(self) -> str:
        return f"{self.day:%d.%m.%Y} {self.starts_at:%H:%M}–{self.ends_at:%H:%M}"


@dataclass(frozen=True, slots=True)
class Target:
    """Окно расписания события: приём/возврат на пункте или выдача/сдача на мероприятии."""

    kind: str  # dropoff | issue | return | pickup
    point: Point | None = None

    @classmethod
    def parse(cls, raw: str) -> Target:
        kind, _, point = raw.partition(".")
        if kind in ("dropoff", "pickup") and point:
            return cls(kind, Point(point))
        if kind in ("issue", "return") and not point:
            return cls(kind)
        raise ValueError(f"bad target: {raw!r}")

    def __str__(self) -> str:
        return f"{self.kind}.{self.point.value}" if self.point else self.kind

    @property
    def slot_type(self) -> SlotType:
        return SlotType.dropoff if self.kind == "dropoff" else SlotType.pickup

    @property
    def title(self) -> str:
        if self.kind == "dropoff":
            return f"Приём велосипедов в Москве — <b>{POINTS[self.point].name}</b>"
        if self.kind == "issue":
            return "<b>Выдача</b> велосипедов на мероприятии"
        if self.kind == "return":
            return "<b>Сдача</b> велосипедов на мероприятии"
        return f"Возврат велосипедов в Москве — <b>{POINTS[self.point].name}</b>"


# Порядок окон: шаги при создании и кнопки в карточке события.
TARGETS = (
    *(Target("dropoff", p) for p in POINTS),
    Target("issue"),
    Target("return"),
    *(Target("pickup", p) for p in POINTS),
)


class AdminError(Exception):
    pass


def parse_price(raw: str) -> Decimal:
    cleaned = raw.strip().replace(",", ".").replace(" ", "")
    try:
        value = Decimal(cleaned)
    except InvalidOperation as exc:
        raise AdminError("Цена должна быть числом, например 9900 или 9900.00") from exc
    if value < 0:
        raise AdminError("Цена не может быть отрицательной.")
    return value.quantize(Decimal("0.01"))


def normalize_name(raw: str) -> str:
    name = " ".join(raw.split())
    if not name:
        raise AdminError("Название не может быть пустым.")
    if len(name) > 255:
        raise AdminError("Название слишком длинное.")
    return name


_TIME_RANGE_RE = re.compile(
    r"^\s*(\d{1,2})(?:[:.](\d{2}))?\s*[-–—]\s*(\d{1,2})(?:[:.](\d{2}))?\s*$"
)


def parse_time_range(raw: str) -> tuple[time, time]:
    """«10:00-20:00», «10.00–20.00», «10-20» → (10:00, 20:00)."""
    match = _TIME_RANGE_RE.match(raw)
    if not match:
        raise AdminError("Не понял время. Пример: 10:00-20:00")
    h1, m1, h2, m2 = match.groups()
    try:
        starts_at = time(int(h1), int(m1 or 0))
        ends_at = time(int(h2), int(m2 or 0))
    except ValueError as exc:
        raise AdminError("Такого времени нет. Пример: 10:00-20:00") from exc
    if starts_at >= ends_at:
        raise AdminError("Начало должно быть раньше конца (в пределах одного дня).")
    return starts_at, ends_at


def moscow_today() -> date:
    return datetime.now(MOSCOW).date()


def min_dropoff_date(today: date | None = None) -> date:
    return (today or moscow_today()) + timedelta(days=1)


def validate_schedule(
    *,
    dropoffs: dict[Point, date],
    issue: date,
    return_: date,
    pickups: dict[Point, date],
) -> None:
    """Порядок дат: приём в Москве < выдача ≤ сдача < возврат в Москве."""
    if not dropoffs:
        raise AdminError("Нужен хотя бы один пункт приёма в Москве.")
    if not pickups:
        raise AdminError("Нужен хотя бы один пункт возврата в Москве.")
    if issue <= max(dropoffs.values()):
        raise AdminError("Выдача на мероприятии должна быть позже приёма в Москве.")
    if return_ < issue:
        raise AdminError("Сдача на мероприятии раньше выдачи.")
    if min(pickups.values()) <= return_:
        raise AdminError("Возврат в Москве должен быть позже сдачи на мероприятии.")


def _validate_event(event: Event) -> None:
    """Проверка расписания события по активным слотам."""
    days: dict[SlotType, dict[Point, date]] = {SlotType.dropoff: {}, SlotType.pickup: {}}
    for slot in event.slots:
        if slot.is_active:
            days[slot.slot_type][slot.point] = slot.service_date
    validate_schedule(
        dropoffs=days[SlotType.dropoff],
        issue=event.issue_date,
        return_=event.return_date,
        pickups=days[SlotType.pickup],
    )


# --- чтение ---

async def list_events(session: AsyncSession, *, limit: int = 30) -> list[Event]:
    stmt = select(Event).order_by(Event.id.desc()).limit(limit)
    return list((await session.scalars(stmt)).all())


async def get_event(session: AsyncSession, event_id: int) -> Event:
    stmt = select(Event).options(selectinload(Event.slots)).where(Event.id == event_id)
    event = (await session.scalars(stmt)).first()
    if event is None:
        raise AdminError("Событие не найдено.")
    return event


async def booking_counts(session: AsyncSession, event_id: int) -> tuple[int, dict[int, int]]:
    """Подтверждённые заявки: всего по событию и по каждому слоту."""
    rows = (
        await session.execute(
            select(Booking.dropoff_slot_id, Booking.pickup_slot_id).where(
                Booking.event_id == event_id,
                Booking.status == BookingStatus.confirmed,
            )
        )
    ).all()
    per_slot: dict[int, int] = {}
    for dropoff_id, pickup_id in rows:
        per_slot[dropoff_id] = per_slot.get(dropoff_id, 0) + 1
        per_slot[pickup_id] = per_slot.get(pickup_id, 0) + 1
    return len(rows), per_slot


def find_slot(event: Event, target: Target) -> EventSlot | None:
    for slot in event.slots:
        if slot.slot_type == target.slot_type and slot.point == target.point:
            return slot
    return None


def target_window(event: Event, target: Target) -> Window | None:
    if target.kind == "issue":
        return Window(event.issue_date, event.issue_starts_at, event.issue_ends_at)
    if target.kind == "return":
        return Window(event.return_date, event.return_starts_at, event.return_ends_at)
    slot = find_slot(event, target)
    return Window(slot.service_date, slot.starts_at, slot.ends_at) if slot else None


def event_issue_window(event: Event) -> Window:
    return target_window(event, Target("issue"))


def event_return_window(event: Event) -> Window:
    return target_window(event, Target("return"))


# --- создание ---

async def create_event(
    session: AsyncSession,
    *,
    name: str,
    price: Decimal,
    dropoffs: dict[Point, date],
    issue: date,
    return_: date,
    pickups: dict[Point, date],
) -> Event:
    """Создаёт событие с закрытой регистрацией — открывает админ после проверки.

    dropoffs/pickups — даты по пунктам; пропущенных пунктов в словаре нет.
    Время везде по умолчанию DEFAULT_STARTS_AT–DEFAULT_ENDS_AT.
    """
    name = normalize_name(name)
    if dropoffs and min(dropoffs.values()) < min_dropoff_date():
        raise AdminError("Приём в Москве должен начинаться не раньше завтрашнего дня.")
    validate_schedule(dropoffs=dropoffs, issue=issue, return_=return_, pickups=pickups)

    event = Event(
        name=name,
        price=price,
        status=EventStatus.published,
        registration_open=False,
        issue_date=issue,
        issue_starts_at=DEFAULT_STARTS_AT,
        issue_ends_at=DEFAULT_ENDS_AT,
        return_date=return_,
        return_starts_at=DEFAULT_STARTS_AT,
        return_ends_at=DEFAULT_ENDS_AT,
        slots=[
            EventSlot(
                point=point,
                slot_type=slot_type,
                service_date=day,
                starts_at=DEFAULT_STARTS_AT,
                ends_at=DEFAULT_ENDS_AT,
                capacity=SLOT_CAPACITY,
                is_active=True,
            )
            for slot_type, days in ((SlotType.dropoff, dropoffs), (SlotType.pickup, pickups))
            for point, day in days.items()
        ],
    )
    try:
        session.add(event)
        await session.commit()
    except SQLAlchemyError:
        await session.rollback()
        raise
    return await get_event(session, event.id)


# --- редактирование ---

async def _commit_valid(session: AsyncSession, event: Event) -> Event:
    try:
        _validate_event(event)
        await session.commit()
    except (AdminError, SQLAlchemyError):
        await session.rollback()
        raise
    return event


async def set_registration_open(session: AsyncSession, event_id: int, is_open: bool) -> Event:
    event = await get_event(session, event_id)
    event.registration_open = is_open
    return await _commit_valid(session, event)


async def rename_event(session: AsyncSession, event_id: int, name: str) -> Event:
    event = await get_event(session, event_id)
    event.name = normalize_name(name)
    return await _commit_valid(session, event)


async def set_event_price(session: AsyncSession, event_id: int, price: Decimal) -> Event:
    """Меняет цену для новых заявок; в уже оформленных цена сохранена своя."""
    event = await get_event(session, event_id)
    event.price = price
    return await _commit_valid(session, event)


async def set_window_day(session: AsyncSession, event_id: int, target: Target, day: date) -> Event:
    """Меняет дату окна. Для пункта без слота — создаёт его со временем по умолчанию."""
    event = await get_event(session, event_id)
    if target.kind == "issue":
        event.issue_date = day
    elif target.kind == "return":
        event.return_date = day
    else:
        slot = find_slot(event, target)
        if slot is None:
            event.slots.append(
                EventSlot(
                    point=target.point,
                    slot_type=target.slot_type,
                    service_date=day,
                    starts_at=DEFAULT_STARTS_AT,
                    ends_at=DEFAULT_ENDS_AT,
                    capacity=SLOT_CAPACITY,
                    is_active=True,  # ORM-default ставится только при flush, а _validate_event смотрит раньше
                )
            )
        else:
            slot.service_date = day
    return await _commit_valid(session, event)


async def set_window_time(
    session: AsyncSession,
    event_id: int,
    target: Target,
    starts_at: time,
    ends_at: time,
) -> Event:
    event = await get_event(session, event_id)
    if target.kind == "issue":
        event.issue_starts_at, event.issue_ends_at = starts_at, ends_at
    elif target.kind == "return":
        event.return_starts_at, event.return_ends_at = starts_at, ends_at
    else:
        slot = find_slot(event, target)
        if slot is None:
            raise AdminError("Пункт ещё не добавлен — сначала выбери дату.")
        slot.starts_at, slot.ends_at = starts_at, ends_at
    return await _commit_valid(session, event)


async def toggle_point(session: AsyncSession, event_id: int, target: Target) -> Event:
    """Включает/выключает пункт. Выключенный не предлагается в новых заявках, старые заявки остаются."""
    event = await get_event(session, event_id)
    slot = find_slot(event, target)
    if slot is None:
        raise AdminError("Пункт ещё не добавлен — сначала выбери дату.")
    slot.is_active = not slot.is_active
    return await _commit_valid(session, event)


# --- форматирование ---

def format_schedule(
    *,
    dropoffs: dict[Point, str],
    issue: str,
    return_: str,
    pickups: dict[Point, str],
) -> str:
    def points_block(labels: dict[Point, str]) -> str:
        return "\n".join(f"  {info.name}: {labels.get(point, '—')}" for point, info in POINTS.items())

    return "\n".join(
        [
            "Приём в Москве:",
            points_block(dropoffs),
            f"Выдача на мероприятии: {issue}",
            f"Сдача на мероприятии: {return_}",
            "Возврат в Москве:",
            points_block(pickups),
        ]
    )


def registration_label(event: Event) -> str:
    return "открыта 🟢" if event.registration_open else "закрыта ⛔"


def format_event_card(event: Event, *, bookings: int) -> str:
    labels: dict[SlotType, dict[Point, str]] = {SlotType.dropoff: {}, SlotType.pickup: {}}
    for slot in event.slots:
        label = Window(slot.service_date, slot.starts_at, slot.ends_at).label()
        labels[slot.slot_type][slot.point] = label if slot.is_active else f"<s>{label}</s> выключен"

    return (
        f"#{event.id} <b>{escape(event.name)}</b>\n"
        f"Цена: {event.price} ₽\n"
        f"Регистрация: {registration_label(event)}\n"
        f"Заявок: {bookings}\n\n"
        + format_schedule(
            dropoffs=labels[SlotType.dropoff],
            issue=event_issue_window(event).label(),
            return_=event_return_window(event).label(),
            pickups=labels[SlotType.pickup],
        )
    )
