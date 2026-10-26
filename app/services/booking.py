from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import (
    Booking,
    BookingStatus,
    Event,
    EventSlot,
    EventStatus,
    SlotType,
)
from app.services.admin import event_issue_window, event_return_window, moscow_today
from app.services.points import POINTS


class BookingError(Exception):
    """Ошибка бизнес-правил при оформлении заявки."""


@dataclass(frozen=True, slots=True)
class BookingDraft:
    user_tg_id: int
    event_id: int
    participant_first_name: str
    participant_last_name: str
    bicycle_brand: str
    bicycle_color: str
    dropoff_slot_id: int
    pickup_slot_id: int
    prestart_service: bool


def normalize_text(value: str, *, field: str, max_len: int) -> str:
    cleaned = " ".join(value.split())
    if not cleaned:
        raise BookingError(f"Поле «{field}» не может быть пустым.")
    if len(cleaned) > max_len:
        raise BookingError(f"Поле «{field}» слишком длинное (макс. {max_len}).")
    return cleaned


def format_slot_label(slot: EventSlot) -> str:
    point = POINTS[slot.point]
    date_str = slot.service_date.strftime("%d.%m.%Y")
    start = slot.starts_at.strftime("%H:%M")
    end = slot.ends_at.strftime("%H:%M")
    return f"{point.name} · {date_str} {start}–{end}"


def format_slot_details(slot: EventSlot) -> str:
    point = POINTS[slot.point]
    lines = [
        f"<b>{point.name}</b>",
        point.address,
        f"{slot.service_date.strftime('%d.%m.%Y')} "
        f"{slot.starts_at.strftime('%H:%M')}–{slot.ends_at.strftime('%H:%M')}",
    ]
    if point.instructions:
        lines.append(point.instructions)
    return "\n".join(lines)


async def list_open_events(session: AsyncSession) -> list[Event]:
    stmt = (
        select(Event)
        .where(
            Event.status == EventStatus.published,
            Event.registration_open.is_(True),
        )
        .order_by(Event.issue_date.asc(), Event.id.asc())
    )
    result = await session.scalars(stmt)
    return list(result.all())


async def get_open_event(session: AsyncSession, event_id: int) -> Event:
    event = await session.get(Event, event_id)
    if event is None:
        raise BookingError("Мероприятие не найдено.")
    _ensure_event_bookable(event)
    return event


def _ensure_event_bookable(event: Event) -> None:
    if event.status != EventStatus.published:
        raise BookingError("Запись на это мероприятие недоступна.")
    if not event.registration_open:
        raise BookingError("Регистрация на мероприятие сейчас закрыта.")


async def _occupied_count(session: AsyncSession, slot_id: int) -> int:
    stmt = select(func.count()).select_from(Booking).where(
        Booking.status == BookingStatus.confirmed,
        or_(
            Booking.dropoff_slot_id == slot_id,
            Booking.pickup_slot_id == slot_id,
        ),
    )
    return int(await session.scalar(stmt) or 0)


async def list_available_slots(
    session: AsyncSession,
    event_id: int,
    slot_type: SlotType,
) -> list[EventSlot]:
    await get_open_event(session, event_id)

    stmt = (
        select(EventSlot)
        .where(
            EventSlot.event_id == event_id,
            EventSlot.slot_type == slot_type,
            EventSlot.is_active.is_(True),
            # Регистрация открывается вручную — прошедшие дни не предлагаем.
            EventSlot.service_date >= moscow_today(),
        )
        .order_by(EventSlot.service_date.asc(), EventSlot.starts_at.asc(), EventSlot.id.asc())
    )
    slots = list((await session.scalars(stmt)).all())
    if not slots:
        return []

    slot_ids = [s.id for s in slots]
    drop_counts = {
        row.slot_id: row.cnt
        for row in (
            await session.execute(
                select(
                    Booking.dropoff_slot_id.label("slot_id"),
                    func.count().label("cnt"),
                )
                .where(
                    Booking.status == BookingStatus.confirmed,
                    Booking.dropoff_slot_id.in_(slot_ids),
                )
                .group_by(Booking.dropoff_slot_id)
            )
        ).all()
    }
    pickup_counts = {
        row.slot_id: row.cnt
        for row in (
            await session.execute(
                select(
                    Booking.pickup_slot_id.label("slot_id"),
                    func.count().label("cnt"),
                )
                .where(
                    Booking.status == BookingStatus.confirmed,
                    Booking.pickup_slot_id.in_(slot_ids),
                )
                .group_by(Booking.pickup_slot_id)
            )
        ).all()
    }

    available: list[EventSlot] = []
    for slot in slots:
        used = drop_counts.get(slot.id, 0) + pickup_counts.get(slot.id, 0)
        if used < slot.capacity:
            available.append(slot)
    return available


async def get_slot_for_event(
    session: AsyncSession,
    *,
    event_id: int,
    slot_id: int,
    slot_type: SlotType,
) -> EventSlot:
    slot = await session.get(EventSlot, slot_id)
    if slot is None:
        raise BookingError("Слот не найден.")
    if slot.event_id != event_id:
        raise BookingError("Слот относится к другому мероприятию.")
    if slot.slot_type != slot_type:
        raise BookingError("Выбран слот неверного типа.")
    if not slot.is_active:
        raise BookingError("Выбранный слот недоступен.")
    if slot.service_date < moscow_today():
        raise BookingError("Дата выбранного слота уже прошла.")
    if slot.starts_at >= slot.ends_at:
        raise BookingError("У слота некорректный временной интервал.")
    return slot


async def _lock_slots(session: AsyncSession, *slot_ids: int) -> None:
    """Lock slot rows in stable order (no joins — safe with FOR UPDATE)."""
    for slot_id in sorted(set(slot_ids)):
        locked = await session.scalar(
            select(EventSlot.id).where(EventSlot.id == slot_id).with_for_update()
        )
        if locked is None:
            raise BookingError("Слот не найден.")


async def _ensure_slot_capacity(
    session: AsyncSession,
    slot: EventSlot,
) -> None:
    used = await _occupied_count(session, slot.id)
    if used >= slot.capacity:
        raise BookingError(f"Слот «{format_slot_label(slot)}» уже заполнен.")


async def create_booking(session: AsyncSession, draft: BookingDraft) -> Booking:
    try:
        first_name = normalize_text(
            draft.participant_first_name, field="Имя", max_len=64
        )
        last_name = normalize_text(
            draft.participant_last_name, field="Фамилия", max_len=64
        )
        brand = normalize_text(draft.bicycle_brand, field="Марка", max_len=128)
        color = normalize_text(draft.bicycle_color, field="Цвет", max_len=64)

        if draft.dropoff_slot_id == draft.pickup_slot_id:
            raise BookingError("Слоты сдачи и получения должны отличаться.")

        event = await session.get(Event, draft.event_id, with_for_update=True)
        if event is None:
            raise BookingError("Мероприятие не найдено.")
        _ensure_event_bookable(event)

        existing = await session.scalar(
            select(Booking.id).where(
                Booking.user_tg_id == draft.user_tg_id,
                Booking.event_id == draft.event_id,
                Booking.status == BookingStatus.confirmed,
            )
        )
        if existing is not None:
            raise BookingError("У вас уже есть активная заявка на это мероприятие.")

        await _lock_slots(session, draft.dropoff_slot_id, draft.pickup_slot_id)
        dropoff = await get_slot_for_event(
            session,
            event_id=draft.event_id,
            slot_id=draft.dropoff_slot_id,
            slot_type=SlotType.dropoff,
        )
        pickup = await get_slot_for_event(
            session,
            event_id=draft.event_id,
            slot_id=draft.pickup_slot_id,
            slot_type=SlotType.pickup,
        )

        await _ensure_slot_capacity(session, dropoff)
        await _ensure_slot_capacity(session, pickup)

        booking = Booking(
            user_tg_id=draft.user_tg_id,
            event_id=event.id,
            participant_first_name=first_name,
            participant_last_name=last_name,
            bicycle_brand=brand,
            bicycle_color=color,
            dropoff_slot_id=dropoff.id,
            pickup_slot_id=pickup.id,
            prestart_service=bool(draft.prestart_service),
            price=Decimal(event.price),
            status=BookingStatus.confirmed,
        )
        session.add(booking)
        await session.commit()
        await session.refresh(booking)
        return booking
    except BookingError:
        await session.rollback()
        raise
    except IntegrityError as exc:
        await session.rollback()
        raise BookingError(
            "Не удалось создать заявку: возможно, слот уже занят "
            "или заявка уже существует."
        ) from exc
    except SQLAlchemyError:
        await session.rollback()
        raise


async def load_booking_summary(session: AsyncSession, booking_id: int) -> Booking:
    stmt = (
        select(Booking)
        .options(
            selectinload(Booking.event),
            selectinload(Booking.dropoff_slot),
            selectinload(Booking.pickup_slot),
        )
        .where(Booking.id == booking_id)
    )
    booking = (await session.scalars(stmt)).unique().first()
    if booking is None:
        raise BookingError("Заявка не найдена.")
    return booking


def build_review_text(
    *,
    event: Event,
    first_name: str,
    last_name: str,
    brand: str,
    color: str,
    dropoff: EventSlot,
    pickup: EventSlot,
    prestart_service: bool,
    price: Decimal | None = None,
) -> str:
    amount = price if price is not None else event.price
    service = "да" if prestart_service else "нет"
    return (
        "<b>Проверьте заявку</b>\n\n"
        f"<b>Мероприятие:</b> {event.name}\n"
        f"<b>Участник:</b> {first_name} {last_name}\n"
        f"<b>Велосипед:</b> {brand}, {color}\n\n"
        f"<b>Сдача в Москве:</b>\n{format_slot_details(dropoff)}\n\n"
        f"<b>Выдача на мероприятии:</b> {event_issue_window(event).label()}\n"
        f"<b>Сдача на мероприятии:</b> {event_return_window(event).label()}\n\n"
        f"<b>Возврат в Москве:</b>\n{format_slot_details(pickup)}\n\n"
        f"<b>Предстартовое ТО:</b> {service}\n"
        f"<b>Стоимость:</b> {amount} ₽"
    )
