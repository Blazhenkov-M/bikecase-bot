from __future__ import annotations

import logging
from datetime import date
from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.database.database import get_session
from app.handlers.admin.filters import IsAdmin
from app.keyboards.admin import (
    admin_menu_kb,
    back_to_event_kb,
    event_card_kb,
    events_list_kb,
    window_kb,
)
from app.keyboards.calendar import calendar_kb
from app.services.admin import (
    AdminError,
    Target,
    booking_counts,
    find_slot,
    format_event_card,
    get_event,
    list_events,
    moscow_today,
    parse_price,
    parse_time_range,
    rename_event,
    set_event_price,
    set_registration_open,
    set_window_day,
    set_window_time,
    target_window,
    toggle_point,
)

logger = logging.getLogger(__name__)
edit_router = Router()
edit_router.message.filter(IsAdmin())
edit_router.callback_query.filter(IsAdmin())


class EditForm(StatesGroup):
    name = State()
    price = State()
    day = State()
    time = State()


def _parse_window_callback(data: str) -> tuple[int, Target]:
    """ad:w*:<event_id>:<target> → (event_id, target)."""
    _, _, event_id, target = data.split(":")
    return int(event_id), Target.parse(target)


async def render_card(message: Message, event_id: int, *, edit: bool) -> None:
    """Карточка события. edit=False — новым сообщением (после ввода текста)."""
    try:
        async for db in get_session():
            event = await get_event(db, event_id)
            total, _ = await booking_counts(db, event_id)
    except AdminError as exc:
        await message.answer(str(exc), reply_markup=admin_menu_kb())
        return
    text = format_event_card(event, bookings=total)
    kb = event_card_kb(event)
    if edit:
        await message.edit_text(text, reply_markup=kb)
    else:
        await message.answer(text, reply_markup=kb)


async def _render_window(message: Message, event_id: int, target: Target) -> None:
    async for db in get_session():
        event = await get_event(db, event_id)
        _, per_slot = await booking_counts(db, event_id)
    window = target_window(event, target)
    slot = find_slot(event, target)

    lines = [f"#{event.id} <b>{escape(event.name)}</b>", target.title, ""]
    if window is None:
        lines.append("Пункт не добавлен.")
    else:
        lines.append(f"Сейчас: <b>{window.label()}</b>")
    if slot is not None:
        if not slot.is_active:
            lines.append("Пункт выключен — в новых заявках не предлагается.")
        lines.append(f"Заявок на этот пункт: {per_slot.get(slot.id, 0)} из {slot.capacity}")
    await message.edit_text(
        "\n".join(lines),
        reply_markup=window_kb(
            event_id,
            target,
            exists=window is not None,
            is_active=slot.is_active if slot else True,
        ),
    )


# --- список и карточка ---

@edit_router.callback_query(F.data == "ad:menu")
async def cb_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await callback.message.edit_text("Админка.", reply_markup=admin_menu_kb())


@edit_router.callback_query(F.data == "ad:list")
async def cb_list(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    try:
        async for db in get_session():
            events = await list_events(db)
    except Exception:
        logger.exception("admin list events failed")
        await callback.message.answer("Не удалось загрузить список событий.")
        return

    if not events:
        await callback.message.edit_text("Событий пока нет.", reply_markup=admin_menu_kb())
        return
    await callback.message.edit_text(
        "События (🟢 — регистрация открыта):",
        reply_markup=events_list_kb(events),
    )


@edit_router.callback_query(F.data.startswith("ad:ev:"))
async def cb_event(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await render_card(callback.message, int(callback.data.split(":")[-1]), edit=True)


@edit_router.callback_query(F.data.startswith("ad:reg:"))
async def cb_toggle_registration(callback: CallbackQuery) -> None:
    event_id = int(callback.data.split(":")[-1])
    try:
        async for db in get_session():
            event = await get_event(db, event_id)
            event = await set_registration_open(db, event_id, not event.registration_open)
    except AdminError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer("Регистрация открыта" if event.registration_open else "Регистрация закрыта")
    await render_card(callback.message, event_id, edit=True)


# --- название и цена ---

@edit_router.callback_query(F.data.startswith("ad:en:"))
async def cb_edit_name(callback: CallbackQuery, state: FSMContext) -> None:
    event_id = int(callback.data.split(":")[-1])
    await state.set_state(EditForm.name)
    await state.update_data(edit_event_id=event_id)
    await callback.answer()
    await callback.message.edit_text("Введи новое название:", reply_markup=back_to_event_kb(event_id))


@edit_router.message(EditForm.name, F.text)
async def msg_edit_name(message: Message, state: FSMContext) -> None:
    event_id = (await state.get_data())["edit_event_id"]
    try:
        async for db in get_session():
            await rename_event(db, event_id, message.text or "")
    except AdminError as exc:
        await message.answer(str(exc), reply_markup=back_to_event_kb(event_id))
        return
    await state.clear()
    await render_card(message, event_id, edit=False)


@edit_router.callback_query(F.data.startswith("ad:ep:"))
async def cb_edit_price(callback: CallbackQuery, state: FSMContext) -> None:
    event_id = int(callback.data.split(":")[-1])
    await state.set_state(EditForm.price)
    await state.update_data(edit_event_id=event_id)
    await callback.answer()
    await callback.message.edit_text(
        "Введи новую цену в рублях.\nВ уже оформленных заявках останется старая цена.",
        reply_markup=back_to_event_kb(event_id),
    )


@edit_router.message(EditForm.price, F.text)
async def msg_edit_price(message: Message, state: FSMContext) -> None:
    event_id = (await state.get_data())["edit_event_id"]
    try:
        price = parse_price(message.text or "")
        async for db in get_session():
            await set_event_price(db, event_id, price)
    except AdminError as exc:
        await message.answer(str(exc), reply_markup=back_to_event_kb(event_id))
        return
    await state.clear()
    await render_card(message, event_id, edit=False)


# --- окна расписания ---

@edit_router.callback_query(F.data.startswith("ad:w:"))
async def cb_window(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    event_id, target = _parse_window_callback(callback.data)
    await _render_window(callback.message, event_id, target)


def _edit_calendar_kb(event_id: int, shown: date):
    # Без нижней границы по смыслу: порядок дат проверяется при сохранении.
    return calendar_kb(
        kind="ed",
        year=shown.year,
        month=shown.month,
        min_date=moscow_today(),
        cancel_callback=f"ad:ev:{event_id}",
    )


@edit_router.callback_query(F.data.startswith("ad:wd:"))
async def cb_window_day(callback: CallbackQuery, state: FSMContext) -> None:
    event_id, target = _parse_window_callback(callback.data)
    await state.set_state(EditForm.day)
    await state.update_data(edit_event_id=event_id, edit_target=str(target))
    await callback.answer()
    await callback.message.edit_text(
        f"{target.title}\nВыбери новую дату:",
        reply_markup=_edit_calendar_kb(event_id, moscow_today()),
    )


@edit_router.callback_query(EditForm.day, F.data.startswith("cal:ed:m:"))
async def cb_edit_calendar_month(callback: CallbackQuery, state: FSMContext) -> None:
    shown = date.fromisoformat(f"{callback.data.split(':')[-1]}-01")
    event_id = (await state.get_data())["edit_event_id"]
    await callback.answer()
    await callback.message.edit_reply_markup(
        reply_markup=_edit_calendar_kb(event_id, max(shown, moscow_today().replace(day=1))),
    )


@edit_router.callback_query(EditForm.day, F.data.startswith("cal:ed:d:"))
async def cb_edit_pick_day(callback: CallbackQuery, state: FSMContext) -> None:
    day = date.fromisoformat(callback.data.split(":")[-1])
    data = await state.get_data()
    event_id, target = data["edit_event_id"], Target.parse(data["edit_target"])
    try:
        async for db in get_session():
            await set_window_day(db, event_id, target, day)
    except AdminError as exc:
        # Остаёмся на календаре — можно выбрать другую дату.
        await callback.answer(str(exc), show_alert=True)
        return
    await state.clear()
    await callback.answer("Дата сохранена")
    await _render_window(callback.message, event_id, target)


@edit_router.callback_query(F.data.startswith("ad:wt:"))
async def cb_window_time(callback: CallbackQuery, state: FSMContext) -> None:
    event_id, target = _parse_window_callback(callback.data)
    await state.set_state(EditForm.time)
    await state.update_data(edit_event_id=event_id, edit_target=str(target))
    await callback.answer()
    await callback.message.edit_text(
        f"{target.title}\nВведи время с–по, например <code>11:00-20:00</code>:",
        reply_markup=back_to_event_kb(event_id),
    )


@edit_router.message(EditForm.time, F.text)
async def msg_window_time(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    event_id, target = data["edit_event_id"], Target.parse(data["edit_target"])
    try:
        starts_at, ends_at = parse_time_range(message.text or "")
        async for db in get_session():
            await set_window_time(db, event_id, target, starts_at, ends_at)
    except AdminError as exc:
        await message.answer(str(exc), reply_markup=back_to_event_kb(event_id))
        return
    await state.clear()
    await render_card(message, event_id, edit=False)


@edit_router.callback_query(F.data.startswith("ad:wx:"))
async def cb_window_toggle(callback: CallbackQuery) -> None:
    event_id, target = _parse_window_callback(callback.data)
    try:
        async for db in get_session():
            await toggle_point(db, event_id, target)
    except AdminError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()
    await _render_window(callback.message, event_id, target)


@edit_router.message(EditForm.name)
@edit_router.message(EditForm.price)
@edit_router.message(EditForm.time)
async def msg_expect_text(message: Message) -> None:
    await message.answer("Пришли текстом или вернись к событию кнопкой выше.")


@edit_router.message(EditForm.day)
async def msg_expect_calendar(message: Message) -> None:
    await message.answer("Выбери дату в календаре выше.")
