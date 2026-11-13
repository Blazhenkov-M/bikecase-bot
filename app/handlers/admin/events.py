from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.handlers.admin.filters import IsAdmin
from app.keyboards.admin import (
    back_cancel_kb,
    back_row,
    cancel_kb,
    confirm_create_kb,
    events_menu_kb,
    finish_confirm_kb,
)
from app.keyboards.calendar import calendar_kb
from app.services.events import (
    LIMITS,
    RANGES,
    WORK_HOURS,
    EventError,
    Ranges,
    count_active_applications,
    create_event,
    finish_event,
    format_event,
    format_limits,
    format_price,
    format_schedule,
    get_current_event,
    get_open_event,
    min_pickup_date,
    moscow_today,
    normalize_name,
    parse_limit,
    parse_price,
    set_registration_open,
)

logger = logging.getLogger(__name__)
router = Router()
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


class CreateEventForm(StatesGroup):
    name = State()
    price = State()
    dates = State()
    limits = State()
    confirm = State()


# --- экран «События» ---

async def events_screen(session: AsyncSession) -> tuple[str, InlineKeyboardMarkup]:
    event = await get_current_event(session)
    if event is None:
        return "Активного события нет.", events_menu_kb(None)
    applications = await count_active_applications(session, event.id)
    return format_event(event, applications=applications), events_menu_kb(event)


@router.callback_query(F.data == "ad:events")
async def cb_events(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    await callback.answer()
    text, kb = await events_screen(session)
    await callback.message.edit_text(text, reply_markup=kb)


# --- статус события ---

def _event_id(callback: CallbackQuery) -> int:
    return int(callback.data.rsplit(":", 1)[-1])


@router.callback_query(F.data.regexp(r"^ad:ev:(open|close):\d+$"))
async def cb_registration(callback: CallbackQuery, session: AsyncSession) -> None:
    is_open = callback.data.startswith("ad:ev:open:")
    try:
        await set_registration_open(session, _event_id(callback), is_open)
    except EventError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer("Регистрация открыта" if is_open else "Регистрация закрыта")
    text, kb = await events_screen(session)
    await callback.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data.regexp(r"^ad:ev:finish:\d+$"))
async def cb_finish(callback: CallbackQuery, session: AsyncSession) -> None:
    try:
        event = await get_open_event(session, _event_id(callback))
    except EventError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text(
        f"Завершить «{escape(event.name)}»?\n\n"
        "Событие уйдёт в архив: регистрация и редактирование станут недоступны, "
        "заявки сохранятся, отчёт можно будет скачать. После этого можно создать новое событие.",
        reply_markup=finish_confirm_kb(event.id),
    )


@router.callback_query(F.data.regexp(r"^ad:ev:finish_ok:\d+$"))
async def cb_finish_ok(callback: CallbackQuery, session: AsyncSession) -> None:
    try:
        await finish_event(session, _event_id(callback))
    except EventError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer("Событие завершено")
    text, kb = await events_screen(session)
    await callback.message.edit_text(text, reply_markup=kb)


# --- создание: название и цена ---

@router.callback_query(F.data == "ad:ev:create")
async def cb_create(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if await get_current_event(session) is not None:
        await callback.answer("Сначала завершите текущее событие.", show_alert=True)
        return
    await callback.answer()
    await state.set_state(CreateEventForm.name)
    await callback.message.edit_text("Введите название мероприятия:", reply_markup=cancel_kb())


@router.message(CreateEventForm.name, F.text)
async def msg_name(message: Message, state: FSMContext) -> None:
    try:
        name = normalize_name(message.text)
    except EventError as exc:
        await message.answer(f"{exc} Ещё раз:", reply_markup=cancel_kb())
        return
    await state.update_data(name=name)
    await state.set_state(CreateEventForm.price)
    await message.answer("Введите цену в рублях (например 9900):", reply_markup=cancel_kb())


@router.message(CreateEventForm.price, F.text)
async def msg_price(message: Message, state: FSMContext) -> None:
    try:
        price = parse_price(message.text)
    except EventError as exc:
        await message.answer(f"{exc} Ещё раз:", reply_markup=cancel_kb())
        return
    await state.update_data(price=str(price), dates=[], limits=[])
    text, kb = await _show_step(state)
    await message.answer(text, reply_markup=kb)


# --- создание: даты ---
# В FSM dates — плоский список ISO-дат: [с, по, с, по, ...] в порядке RANGES,
# limits — список чисел в порядке LIMITS.

def _dates(data: dict) -> list[date]:
    return [date.fromisoformat(d) for d in data["dates"]]


def _ranges(dates: list[date]) -> Ranges:
    """Только полностью заполненные диапазоны."""
    return {RANGES[i // 2].field: (dates[i], dates[i + 1]) for i in range(0, len(dates) - 1, 2)}


def _min_day(dates: list[date]) -> date:
    if len(dates) % 2:  # выбираем «по» — не раньше «с»
        return dates[-1]
    if RANGES[len(dates) // 2].is_pickup:
        return min_pickup_date(_ranges(dates))
    return moscow_today()


def _header(data: dict) -> str:
    return f"<b>{escape(data['name'])}</b>, {format_price(Decimal(data['price']))}\nВремя работы точек: {WORK_HOURS}"


def _dates_text(data: dict) -> str:
    dates = _dates(data)
    step = RANGES[len(dates) // 2]
    filled = format_schedule(_ranges(dates))
    if len(dates) % 2:
        current = f"{step.title}: с <b>{dates[-1]:%d.%m.%Y}</b>\nВыберите <b>последний</b> день:"
    else:
        current = f"{step.title}\nВыберите <b>первый</b> день:"
    parts = [_header(data), filled, f"Шаг {len(dates) // 2 + 1}/{len(RANGES)}. {current}"]
    return "\n\n".join(part for part in parts if part)


def _dates_kb(data: dict, shown: date | None = None) -> InlineKeyboardMarkup:
    dates = _dates(data)
    min_day = _min_day(dates)
    shown = max(shown or min_day, min_day.replace(day=1))
    return calendar_kb(
        kind="ev",
        year=shown.year,
        month=shown.month,
        min_date=min_day,
        cancel_callback="ad:events",
        extra_rows=[back_row()] if dates else None,
    )


def _limits(data: dict) -> dict[str, int]:
    """Только уже введённые лимиты."""
    return dict(zip(LIMITS, data["limits"]))


async def _show_step(state: FSMContext) -> tuple[str, InlineKeyboardMarkup]:
    """Текущий шаг после цены: даты → лимиты Крылатского → сводка с подтверждением."""
    data = await state.get_data()
    if len(data["dates"]) < 2 * len(RANGES):
        await state.set_state(CreateEventForm.dates)
        return _dates_text(data), _dates_kb(data)

    limits = _limits(data)
    summary = [_header(data), format_schedule(_ranges(_dates(data))), format_limits(limits)]
    if len(limits) < len(LIMITS):
        await state.set_state(CreateEventForm.limits)
        title = list(LIMITS.values())[len(limits)]
        summary.append(f"{title}.\nВведите число (например 20):")
        return "\n\n".join(part for part in summary if part), back_cancel_kb()

    await state.set_state(CreateEventForm.confirm)
    summary.append("Создать событие? Регистрация откроется сразу.")
    return "\n\n".join(summary), confirm_create_kb()


@router.callback_query(CreateEventForm.dates, F.data.startswith("cal:ev:m:"))
async def cb_dates_month(callback: CallbackQuery, state: FSMContext) -> None:
    shown = date.fromisoformat(f"{callback.data.split(':')[-1]}-01")
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=_dates_kb(await state.get_data(), shown))


@router.callback_query(CreateEventForm.dates, F.data.startswith("cal:ev:d:"))
async def cb_dates_day(callback: CallbackQuery, state: FSMContext) -> None:
    day = date.fromisoformat(callback.data.split(":")[-1])
    data = await state.get_data()
    if day < _min_day(_dates(data)):
        await callback.answer("Эта дата недоступна.", show_alert=True)
        return
    await callback.answer()
    await state.update_data(dates=[*data["dates"], day.isoformat()])
    text, kb = await _show_step(state)
    await callback.message.edit_text(text, reply_markup=kb)


@router.message(CreateEventForm.limits, F.text)
async def msg_limit(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    try:
        limit = parse_limit(message.text)
    except EventError as exc:
        await message.answer(f"{exc} Ещё раз:", reply_markup=back_cancel_kb())
        return
    await state.update_data(limits=[*data["limits"], limit])
    text, kb = await _show_step(state)
    await message.answer(text, reply_markup=kb)


@router.callback_query(CreateEventForm.dates, F.data == "ad:ev:back")
@router.callback_query(CreateEventForm.limits, F.data == "ad:ev:back")
@router.callback_query(CreateEventForm.confirm, F.data == "ad:ev:back")
async def cb_step_back(callback: CallbackQuery, state: FSMContext) -> None:
    """Отменяет последний введённый шаг: лимит, а если их нет — дату."""
    data = await state.get_data()
    await callback.answer()
    if data["limits"]:
        await state.update_data(limits=data["limits"][:-1])
    else:
        await state.update_data(dates=data["dates"][:-1])
    text, kb = await _show_step(state)
    await callback.message.edit_text(text, reply_markup=kb)


# --- создание: подтверждение ---

@router.callback_query(CreateEventForm.confirm, F.data == "ad:ev:save")
async def cb_save(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    try:
        await create_event(
            session,
            name=data["name"],
            price=Decimal(data["price"]),
            ranges=_ranges(_dates(data)),
            limits=_limits(data),
        )
    except EventError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    except Exception:
        logger.exception("create event failed")
        await callback.answer("Не удалось создать событие.", show_alert=True)
        return
    await state.clear()
    await callback.answer("Событие создано")
    text, kb = await events_screen(session)
    await callback.message.edit_text(text, reply_markup=kb)


# --- неожиданный ввод ---

@router.message(CreateEventForm.name)
@router.message(CreateEventForm.price)
async def msg_expect_text(message: Message) -> None:
    await message.answer("Пришлите текстом или нажмите «Отмена».", reply_markup=cancel_kb())


@router.message(CreateEventForm.limits)
async def msg_expect_limit(message: Message) -> None:
    await message.answer("Пришлите число текстом или нажмите «Отмена».", reply_markup=back_cancel_kb())


@router.message(CreateEventForm.dates)
@router.message(CreateEventForm.confirm)
async def msg_expect_buttons(message: Message) -> None:
    await message.answer("Используйте кнопки выше или нажмите «Отмена».")
