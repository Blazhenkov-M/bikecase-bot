from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from html import escape

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import Application, ApplicationStatus, Event, EventStatus, Point, User
from app.services.events import WORK_HOURS, format_price, get_current_event, moscow_today
from app.services.points import POINTS, point_dates


class ApplicationError(Exception):
    pass


class DayUnavailableError(ApplicationError):
    """Выбранный день в Крылатском недоступен; kind — dropoff | pickup."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")


# Текстовые поля заявки: поле -> (подпись, максимальная длина)
TEXT_FIELDS: dict[str, tuple[str, int]] = {
    "first_name": ("Имя", 64),
    "last_name": ("Фамилия", 64),
    "phone": ("Телефон", 32),
    "bicycle_brand": ("Марка велосипеда", 128),
    "bicycle_color": ("Цвет велосипеда", 64),
}

_PHONE_RE = re.compile(r"^\+?[\d\s\-()]+$")


def normalize_field(field: str, raw: str) -> str:
    label, max_len = TEXT_FIELDS[field]
    value = " ".join(raw.split())
    if not value:
        raise ApplicationError(f"{label}: пустое значение.")
    if len(value) > max_len:
        raise ApplicationError(f"{label}: слишком длинно (максимум {max_len} символов).")
    if field == "phone":
        digits = sum(ch.isdigit() for ch in value)
        if not _PHONE_RE.match(value) or not 5 <= digits <= 15:
            raise ApplicationError("Не похоже на номер телефона. Пример: +7 999 123-45-67")
    return value


def needs_day(point: Point | str) -> bool:
    """В Крылатском клиент записывается на конкретный день, в мастерских — нет."""
    return Point(point) == Point.krylatskoe


def format_day(day: date) -> str:
    return f"{day:%d.%m}, {WEEKDAYS[day.weekday()]}"


def format_point(event: Event, point: Point, kind: str, day: date | None = None) -> str:
    """Точка с датами: выбранный день либо весь диапазон точки."""
    # Без года — чтобы подпись помещалась в кнопку.
    if day is not None:
        return f"{POINTS[point].name} ({format_day(day)})"
    start, end = point_dates(event, point, kind)
    dates = f"{start:%d.%m}" if start == end else f"{start:%d.%m}–{end:%d.%m}"
    return f"{POINTS[point].name} ({dates})"


def _field_day(fields: dict, kind: str) -> date | None:
    raw = fields.get(f"{kind}_date")
    return date.fromisoformat(raw) if raw else None


def format_application(fields: dict, event: Event) -> str:
    """fields — словарь полей заявки (из FSM или из Application)."""
    lines = [f"<b>{escape(event.name)}</b>, {format_price(event.price)}", ""]
    lines += [f"{label}: {escape(fields[field])}" for field, (label, _) in TEXT_FIELDS.items()]
    days = {kind: _field_day(fields, kind) for kind in ("dropoff", "pickup")}
    if all(days.values()):
        hint = "Приезжайте в выбранные дни."
    elif any(days.values()):
        hint = "В Крылатское приезжайте в выбранный день, в мастерскую — в любой день диапазона."
    else:
        hint = "Приезжайте в любой день диапазона."
    lines += [
        f"Сдача: {format_point(event, Point(fields['dropoff_point']), 'dropoff', days['dropoff'])}",
        f"Получение: {format_point(event, Point(fields['pickup_point']), 'pickup', days['pickup'])}",
        "",
        f"{hint} Время работы точек {WORK_HOURS}.",
    ]
    return "\n".join(lines)


def application_fields(application: Application) -> dict:
    fields = {field: getattr(application, field) for field in TEXT_FIELDS}
    fields["dropoff_point"] = application.dropoff_point.value
    fields["pickup_point"] = application.pickup_point.value
    for kind in ("dropoff", "pickup"):
        day = getattr(application, f"{kind}_date")
        fields[f"{kind}_date"] = day.isoformat() if day else None
    return fields


# --- дни и лимиты Крылатского ---

async def day_counts(
    session: AsyncSession, event_id: int, kind: str, *, exclude_application_id: int | None = None
) -> dict[date, int]:
    """Сколько активных заявок записано на каждый день Крылатского; kind — dropoff | pickup."""
    day = getattr(Application, f"{kind}_date")
    stmt = (
        select(day, func.count())
        .where(
            Application.event_id == event_id,
            Application.status == ApplicationStatus.active,
            day.is_not(None),
        )
        .group_by(day)
    )
    if exclude_application_id is not None:
        stmt = stmt.where(Application.id != exclude_application_id)
    return {row[0]: row[1] for row in await session.execute(stmt)}


async def free_days(
    session: AsyncSession, event: Event, kind: str, *, exclude_application_id: int | None = None
) -> list[date]:
    """Дни Крылатского, на которые ещё можно записаться: не прошедшие и не заполненные."""
    start, end = point_dates(event, Point.krylatskoe, kind)
    limit = getattr(event, f"krylatskoe_{kind}_limit")
    counts = await day_counts(session, event.id, kind, exclude_application_id=exclude_application_id)
    today = moscow_today()
    days = (start + timedelta(days=n) for n in range((end - start).days + 1))
    return [d for d in days if d >= today and (limit is None or counts.get(d, 0) < limit)]


async def _lock_event(session: AsyncSession, event_id: int) -> Event:
    """Блокирует строку события до конца транзакции: проверка лимита и запись идут по одному."""
    return await session.scalar(
        select(Event).where(Event.id == event_id).with_for_update().execution_options(populate_existing=True)
    )


async def _checked_day(
    session: AsyncSession,
    event: Event,
    kind: str,
    point: Point,
    day: date | None,
    *,
    exclude_application_id: int | None = None,
) -> date | None:
    """День для сохранения в заявку. Вызывать под блокировкой события."""
    if not needs_day(point):
        return None
    if day is None:
        raise DayUnavailableError(kind, "Для Крылатского нужно выбрать день.")
    if day not in await free_days(session, event, kind, exclude_application_id=exclude_application_id):
        raise DayUnavailableError(kind, "На этот день в Крылатском мест уже нет — выберите другой.")
    return day


async def get_open_registration_event(session: AsyncSession) -> Event:
    event = await get_current_event(session)
    if event is None or event.status != EventStatus.active:
        raise ApplicationError("Сейчас регистрация закрыта.")
    return event


async def get_active_application(session: AsyncSession, user_id: int, event_id: int) -> Application | None:
    return await session.scalar(
        select(Application).where(
            Application.user_tg_id == user_id,
            Application.event_id == event_id,
            Application.status == ApplicationStatus.active,
        )
    )


async def has_consent(session: AsyncSession, user_id: int) -> bool:
    user = await session.get(User, user_id)
    return user is not None and user.pd_consent_at is not None


async def give_consent(session: AsyncSession, user_id: int) -> None:
    user = await session.get(User, user_id)
    if user.pd_consent_at is None:
        user.pd_consent_at = datetime.now(timezone.utc)
        await session.commit()


async def create_application(session: AsyncSession, user_id: int, event_id: int, fields: dict) -> Application:
    event = await get_open_registration_event(session)
    if event.id != event_id:
        raise ApplicationError("Событие изменилось, оформите заявку заново.")
    if not await has_consent(session, user_id):
        raise ApplicationError("Нужно согласие на обработку персональных данных.")

    event = await _lock_event(session, event.id)
    points = {kind: Point(fields[f"{kind}_point"]) for kind in ("dropoff", "pickup")}
    days = {
        kind: await _checked_day(session, event, kind, point, _field_day(fields, kind))
        for kind, point in points.items()
    }
    application = Application(
        event_id=event.id,
        user_tg_id=user_id,
        **{field: fields[field] for field in TEXT_FIELDS},
        dropoff_point=points["dropoff"],
        pickup_point=points["pickup"],
        dropoff_date=days["dropoff"],
        pickup_date=days["pickup"],
    )
    session.add(application)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ApplicationError("У вас уже есть заявка на это событие — она в «Мои заявки».") from exc
    return application


# --- «Мои заявки» ---

async def list_user_applications(session: AsyncSession, user_id: int) -> list[Application]:
    """Неотменённые заявки клиента, новые сверху."""
    result = await session.scalars(
        select(Application)
        .options(selectinload(Application.event))
        .where(Application.user_tg_id == user_id, Application.status == ApplicationStatus.active)
        .order_by(Application.created_at.desc())
        .limit(20)
    )
    return list(result)


async def get_user_application(session: AsyncSession, user_id: int, application_id: int) -> Application:
    application = await session.scalar(
        select(Application)
        .options(selectinload(Application.event))
        .where(Application.id == application_id, Application.user_tg_id == user_id)
    )
    if application is None or application.status != ApplicationStatus.active:
        raise ApplicationError("Заявка не найдена или отменена.")
    return application


def is_editable(application: Application) -> bool:
    return application.event.status == EventStatus.active


async def get_editable_application(session: AsyncSession, user_id: int, application_id: int) -> Application:
    application = await get_user_application(session, user_id, application_id)
    if not is_editable(application):
        raise ApplicationError("Регистрация закрыта — изменить заявку уже нельзя. Напишите в поддержку.")
    return application


async def update_application_field(
    session: AsyncSession, user_id: int, application_id: int, field: str, raw: str
) -> Application:
    if field not in TEXT_FIELDS:
        raise ApplicationError("Неизвестное поле.")
    application = await get_editable_application(session, user_id, application_id)
    setattr(application, field, normalize_field(field, raw))
    await session.commit()
    return application


async def update_application_point(
    session: AsyncSession, user_id: int, application_id: int, kind: str, point: Point, day: date | None
) -> Application:
    """Меняет точку сдачи/получения; для Крылатского — вместе с днём."""
    application = await get_editable_application(session, user_id, application_id)
    event = await _lock_event(session, application.event_id)
    # Своя же заявка место не занимает — иначе нельзя было бы пересохранить тот же день.
    day = await _checked_day(session, event, kind, point, day, exclude_application_id=application.id)
    setattr(application, f"{kind}_point", point)
    setattr(application, f"{kind}_date", day)
    await session.commit()
    return application


async def cancel_application(session: AsyncSession, user_id: int, application_id: int) -> Application:
    application = await get_editable_application(session, user_id, application_id)
    application.status = ApplicationStatus.cancelled
    await session.commit()
    return application
