from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from html import escape

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Application, ApplicationStatus, Event, EventStatus

MOSCOW = timezone(timedelta(hours=3))
WORK_HOURS = "11:00–20:00"


class EventError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class DateRange:
    field: str  # префикс колонок events: <field>_from / <field>_to
    title: str

    @property
    def is_pickup(self) -> bool:
        return self.field.endswith("_pickup")


# Порядок = порядок шагов при создании события и строк в карточке.
RANGES: tuple[DateRange, ...] = (
    DateRange("workshop_dropoff", "Приём — Заповедная и Староватутинский"),
    DateRange("krylatskoe_dropoff", "Приём — Крылатское"),
    DateRange("workshop_pickup", "Выдача — Заповедная и Староватутинский"),
    DateRange("krylatskoe_pickup", "Выдача — Крылатское"),
)

STATUS_TITLES = {
    EventStatus.active: "🟢 регистрация открыта",
    EventStatus.registration_closed: "🔴 регистрация закрыта",
    EventStatus.finished: "⚪️ завершено",
}

Ranges = dict[str, tuple[date, date]]

# Лимиты мест в день в Крылатском: kind (dropoff | pickup) -> подпись.
# Порядок = порядок шагов при создании события.
LIMITS: dict[str, str] = {
    "dropoff": "Мест в день на приём — Крылатское",
    "pickup": "Мест в день на выдачу — Крылатское",
}
MAX_LIMIT = 1000
Limits = dict[str, int]


def moscow_today() -> date:
    return datetime.now(MOSCOW).date()


def parse_price(raw: str) -> Decimal:
    cleaned = raw.strip().replace(",", ".").replace(" ", "")
    try:
        value = Decimal(cleaned)
    except InvalidOperation as exc:
        raise EventError("Цена должна быть числом, например 9900.") from exc
    if not value.is_finite() or value < 0:
        raise EventError("Цена не может быть отрицательной.")
    return value.quantize(Decimal("0.01"))


def parse_limit(raw: str) -> int:
    cleaned = raw.strip().replace(" ", "")
    if not cleaned.isdecimal():
        raise EventError("Лимит должен быть целым числом, например 20.")
    value = int(cleaned)
    if not 1 <= value <= MAX_LIMIT:
        raise EventError(f"Лимит должен быть от 1 до {MAX_LIMIT}.")
    return value


def normalize_name(raw: str) -> str:
    name = " ".join(raw.split())
    if not name:
        raise EventError("Название не может быть пустым.")
    if len(name) > 255:
        raise EventError("Название слишком длинное.")
    return name


def format_price(price: Decimal) -> str:
    if price == price.to_integral_value():
        return f"{int(price):,} ₽".replace(",", " ")
    return f"{price:,.2f} ₽".replace(",", " ")


def format_range(start: date, end: date) -> str:
    if start == end:
        return f"{start:%d.%m.%Y}"
    return f"{start:%d.%m.%Y} – {end:%d.%m.%Y}"


def event_ranges(event: Event) -> Ranges:
    return {r.field: (getattr(event, f"{r.field}_from"), getattr(event, f"{r.field}_to")) for r in RANGES}


def format_schedule(ranges: Ranges) -> str:
    lines = [
        f"{r.title}: <b>{format_range(*ranges[r.field])}</b>"
        for r in RANGES
        if r.field in ranges
    ]
    return "\n".join(lines)


def event_limits(event: Event) -> dict[str, int | None]:
    return {kind: getattr(event, f"krylatskoe_{kind}_limit") for kind in LIMITS}


def format_limits(limits: dict[str, int | None]) -> str:
    return "\n".join(
        f"{title}: <b>{limits[kind] if limits[kind] is not None else 'не задано'}</b>"
        for kind, title in LIMITS.items()
        if kind in limits
    )


def format_event(event: Event, *, applications: int | None = None) -> str:
    lines = [
        f"<b>{escape(event.name)}</b>",
        f"Цена: {format_price(event.price)}",
        f"Статус: {STATUS_TITLES[event.status]}",
        "",
        format_schedule(event_ranges(event)),
        format_limits(event_limits(event)),
        f"Время работы точек: {WORK_HOURS}",
    ]
    if applications is not None:
        lines += ["", f"Активных заявок: {applications}"]
    return "\n".join(lines)


def min_pickup_date(ranges: Ranges) -> date:
    """Выдача начинается не раньше дня после окончания всех приёмов."""
    return max(end for field, (_, end) in ranges.items() if field.endswith("_dropoff")) + timedelta(days=1)


def validate_ranges(ranges: Ranges) -> None:
    if set(ranges) != {r.field for r in RANGES}:
        raise EventError("Заполнены не все даты.")
    for r in RANGES:
        start, end = ranges[r.field]
        if start > end:
            raise EventError(f"{r.title}: дата начала позже даты окончания.")
    first_pickup = min(ranges[r.field][0] for r in RANGES if r.is_pickup)
    if first_pickup < min_pickup_date(ranges):
        raise EventError("Выдача должна начинаться после окончания приёма.")


async def get_current_event(session: AsyncSession) -> Event | None:
    """Незавершённое событие — оно одно (гарантирует индекс uq_events_single_current)."""
    return await session.scalar(select(Event).where(Event.status != EventStatus.finished))


async def count_active_applications(session: AsyncSession, event_id: int) -> int:
    return await session.scalar(
        select(func.count())
        .select_from(Application)
        .where(Application.event_id == event_id, Application.status == ApplicationStatus.active)
    )


async def create_event(
    session: AsyncSession, *, name: str, price: Decimal, ranges: Ranges, limits: Limits
) -> Event:
    validate_ranges(ranges)
    if set(limits) != set(LIMITS):
        raise EventError("Заполнены не все лимиты.")
    if await get_current_event(session) is not None:
        raise EventError("Сначала завершите текущее событие.")

    event = Event(name=name, price=price, status=EventStatus.active)
    for kind, limit in limits.items():
        setattr(event, f"krylatskoe_{kind}_limit", limit)
    for field, (start, end) in ranges.items():
        setattr(event, f"{field}_from", start)
        setattr(event, f"{field}_to", end)
    session.add(event)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise EventError("Сначала завершите текущее событие.") from exc
    return event


# --- управление существующим событием ---

async def get_open_event(session: AsyncSession, event_id: int, *, lock: bool = False) -> Event:
    """Событие, которое ещё можно менять (не завершено)."""
    event = await session.get(Event, event_id, with_for_update=lock)
    if event is None:
        raise EventError("Событие не найдено.")
    if event.status == EventStatus.finished:
        raise EventError("Событие уже завершено.")
    return event


async def set_registration_open(session: AsyncSession, event_id: int, is_open: bool) -> Event:
    event = await get_open_event(session, event_id)
    event.status = EventStatus.active if is_open else EventStatus.registration_closed
    await session.commit()
    return event


async def finish_event(session: AsyncSession, event_id: int) -> Event:
    event = await get_open_event(session, event_id)
    event.status = EventStatus.finished
    await session.commit()
    return event


async def rename_event(session: AsyncSession, event_id: int, raw_name: str) -> Event:
    name = normalize_name(raw_name)
    event = await get_open_event(session, event_id)
    event.name = name
    await session.commit()
    return event


async def set_event_price(session: AsyncSession, event_id: int, raw_price: str) -> Event:
    price = parse_price(raw_price)
    event = await get_open_event(session, event_id)
    event.price = price
    await session.commit()
    return event


async def set_event_range(session: AsyncSession, event_id: int, field: str, start: date, end: date) -> Event:
    # Блокируем событие: параллельная заявка на день Крылатского ждёт и увидит уже новые даты.
    event = await get_open_event(session, event_id, lock=True)
    try:
        validate_ranges({**event_ranges(event), field: (start, end)})
        if field.startswith("krylatskoe_"):
            # Клиенты записаны на конкретные дни — не даём оставить их вне диапазона.
            day_column = getattr(Application, f"{field.removeprefix('krylatskoe_')}_date")
            outside = await session.scalar(
                select(func.count())
                .select_from(Application)
                .where(
                    Application.event_id == event.id,
                    Application.status == ApplicationStatus.active,
                    day_column.is_not(None),
                    ~day_column.between(start, end),
                )
            )
            if outside:
                raise EventError(f"На дни вне нового диапазона уже есть заявки: {outside}.")
    except EventError:
        await session.rollback()
        raise
    setattr(event, f"{field}_from", start)
    setattr(event, f"{field}_to", end)
    await session.commit()
    return event


async def set_event_limit(session: AsyncSession, event_id: int, kind: str, raw_limit: str) -> Event:
    """Уже принятые заявки не трогаем: уменьшенный лимит лишь закрывает запись на заполненные дни."""
    limit = parse_limit(raw_limit)
    event = await get_open_event(session, event_id)
    setattr(event, f"krylatskoe_{kind}_limit", limit)
    await session.commit()
    return event
