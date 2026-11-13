from __future__ import annotations

import logging
from datetime import date

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.handlers.admin.filters import IsAdmin
from app.keyboards.admin import cancel_kb, edit_menu_kb
from app.keyboards.calendar import calendar_kb
from app.services.events import (
    LIMITS,
    RANGES,
    EventError,
    event_ranges,
    format_event,
    get_open_event,
    moscow_today,
    rename_event,
    set_event_limit,
    set_event_price,
    set_event_range,
)

logger = logging.getLogger(__name__)
router = Router()
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


class EditEventForm(StatesGroup):
    name = State()
    price = State()
    limit = State()
    range = State()


def _menu_callback(event_id: int) -> str:
    return f"ad:ed:{event_id}"


async def _edit_menu(session: AsyncSession, event_id: int) -> tuple[str, InlineKeyboardMarkup]:
    event = await get_open_event(session, event_id)
    text = f"{format_event(event)}\n\nЧто изменить?"
    return text, edit_menu_kb(event.id, [r.title for r in RANGES], LIMITS)


# --- меню редактирования ---

@router.callback_query(F.data.regexp(r"^ad:ed:\d+$"))
async def cb_edit_menu(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    try:
        text, kb = await _edit_menu(session, int(callback.data.split(":")[2]))
    except EventError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text(text, reply_markup=kb)


# --- название и цена ---

@router.callback_query(F.data.regexp(r"^ad:ed:\d+:(name|price)$"))
async def cb_edit_text_field(callback: CallbackQuery, state: FSMContext) -> None:
    _, _, event_id, field = callback.data.split(":")
    event_id = int(event_id)
    await state.set_state(EditEventForm.name if field == "name" else EditEventForm.price)
    await state.update_data(edit_event_id=event_id)
    await callback.answer()
    prompt = "Введите новое название:" if field == "name" else "Введите новую цену в рублях:"
    await callback.message.edit_text(prompt, reply_markup=cancel_kb(_menu_callback(event_id)))


@router.message(EditEventForm.name, F.text)
@router.message(EditEventForm.price, F.text)
async def msg_edit_text_field(message: Message, state: FSMContext, session: AsyncSession) -> None:
    event_id = (await state.get_data())["edit_event_id"]
    update = rename_event if await state.get_state() == EditEventForm.name.state else set_event_price
    try:
        await update(session, event_id, message.text)
        text, kb = await _edit_menu(session, event_id)
    except EventError as exc:
        await message.answer(f"{exc} Ещё раз:", reply_markup=cancel_kb(_menu_callback(event_id)))
        return
    await state.clear()
    await message.answer(f"Сохранено ✅\n\n{text}", reply_markup=kb)


# --- лимиты Крылатского ---

@router.callback_query(F.data.regexp(r"^ad:ed:\d+:l(dropoff|pickup)$"))
async def cb_edit_limit(callback: CallbackQuery, state: FSMContext) -> None:
    _, _, event_id, raw = callback.data.split(":")
    event_id, kind = int(event_id), raw[1:]
    await state.set_state(EditEventForm.limit)
    await state.update_data(edit_event_id=event_id, edit_limit=kind)
    await callback.answer()
    await callback.message.edit_text(
        f"{LIMITS[kind]}.\nВведите новое число. Уже принятые заявки сохранятся, даже если их больше.",
        reply_markup=cancel_kb(_menu_callback(event_id)),
    )


@router.message(EditEventForm.limit, F.text)
async def msg_edit_limit(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    event_id = data["edit_event_id"]
    try:
        await set_event_limit(session, event_id, data["edit_limit"], message.text)
        text, kb = await _edit_menu(session, event_id)
    except EventError as exc:
        await message.answer(f"{exc} Ещё раз:", reply_markup=cancel_kb(_menu_callback(event_id)))
        return
    await state.clear()
    await message.answer(f"Сохранено ✅\n\n{text}", reply_markup=kb)


# --- диапазоны дат ---
# В FSM: edit_event_id, edit_range (индекс в RANGES), edit_from (ISO, после выбора первого дня).

def _range_kb(data: dict, shown: date | None = None) -> InlineKeyboardMarkup:
    if data.get("edit_from"):
        min_day = date.fromisoformat(data["edit_from"])
    else:
        # Можно оставить уже прошедшее начало, например чтобы продлить идущий приём.
        min_day = min(date.fromisoformat(data["current_from"]), moscow_today())
    shown = max(shown or min_day, min_day.replace(day=1))
    return calendar_kb(
        kind="ed",
        year=shown.year,
        month=shown.month,
        min_date=min_day,
        cancel_callback=_menu_callback(data["edit_event_id"]),
    )


def _range_text(data: dict) -> str:
    r = RANGES[data["edit_range"]]
    if data.get("edit_from"):
        return f"{r.title}: с <b>{date.fromisoformat(data['edit_from']):%d.%m.%Y}</b>\nВыберите <b>последний</b> день:"
    return f"{r.title}\nСейчас: <b>{data['current_label']}</b>\n\nВыберите <b>первый</b> день:"


@router.callback_query(F.data.regexp(r"^ad:ed:\d+:r\d$"))
async def cb_edit_range(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    _, _, event_id, raw = callback.data.split(":")
    idx = int(raw[1:])
    try:
        event = await get_open_event(session, int(event_id))
    except EventError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    start, end = event_ranges(event)[RANGES[idx].field]
    await state.set_state(EditEventForm.range)
    await state.set_data({
        "edit_event_id": event.id,
        "edit_range": idx,
        "current_from": start.isoformat(),
        "current_label": f"{start:%d.%m.%Y} – {end:%d.%m.%Y}",
    })
    data = await state.get_data()
    await callback.answer()
    await callback.message.edit_text(_range_text(data), reply_markup=_range_kb(data))


@router.callback_query(EditEventForm.range, F.data.startswith("cal:ed:m:"))
async def cb_range_month(callback: CallbackQuery, state: FSMContext) -> None:
    shown = date.fromisoformat(f"{callback.data.split(':')[-1]}-01")
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=_range_kb(await state.get_data(), shown))


@router.callback_query(EditEventForm.range, F.data.startswith("cal:ed:d:"))
async def cb_range_day(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    day = date.fromisoformat(callback.data.split(":")[-1])
    data = await state.get_data()

    if not data.get("edit_from"):
        await callback.answer()
        await state.update_data(edit_from=day.isoformat())
        data = await state.get_data()
        await callback.message.edit_text(_range_text(data), reply_markup=_range_kb(data))
        return

    start = date.fromisoformat(data["edit_from"])
    if day < start:
        await callback.answer("Эта дата недоступна.", show_alert=True)
        return
    try:
        await set_event_range(session, data["edit_event_id"], RANGES[data["edit_range"]].field, start, day)
    except EventError as exc:
        # Начинаем выбор диапазона заново.
        await state.update_data(edit_from=None)
        await callback.answer(str(exc), show_alert=True)
        data = await state.get_data()
        await callback.message.edit_text(_range_text(data), reply_markup=_range_kb(data))
        return

    await state.clear()
    await callback.answer("Сохранено")
    text, kb = await _edit_menu(session, data["edit_event_id"])
    await callback.message.edit_text(text, reply_markup=kb)


# --- неожиданный ввод ---

@router.message(EditEventForm.name)
@router.message(EditEventForm.price)
@router.message(EditEventForm.limit)
async def msg_expect_text(message: Message) -> None:
    await message.answer("Пришлите текстом или нажмите «Отмена».")


@router.message(EditEventForm.range)
async def msg_expect_calendar(message: Message) -> None:
    await message.answer("Выберите дату в календаре выше.")
