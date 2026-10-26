from __future__ import annotations

import logging
from datetime import date, timedelta
from html import escape
from decimal import Decimal

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from app.database.database import get_session
from app.database.models import Point
from app.handlers.admin.edit import render_card
from app.handlers.admin.filters import IsAdmin
from app.keyboards.admin import admin_cancel_kb, admin_confirm_kb, admin_menu_kb, point_step_rows
from app.keyboards.calendar import CALENDAR_IGNORE, calendar_kb
from app.services.admin import (
    DEFAULT_ENDS_AT,
    DEFAULT_STARTS_AT,
    TARGETS,
    AdminError,
    Target,
    Window,
    create_event,
    format_schedule,
    min_dropoff_date,
    normalize_name,
    parse_price,
)

logger = logging.getLogger(__name__)
admin_router = Router()


class AdminCreateForm(StatesGroup):
    name = State()
    price = State()
    day = State()
    confirm = State()


# Второй этап создания события: только даты, время — по умолчанию.
STEPS = TARGETS


admin_router.message.filter(IsAdmin())
admin_router.callback_query.filter(IsAdmin())


# --- данные шагов в FSM ---
# days: {"dropoff": {point: iso}, "issue": iso, "return": iso, "pickup": {point: iso}}

def _days(data: dict) -> dict:
    return data.get("days") or {"dropoff": {}, "pickup": {}}


def _point_days(data: dict, kind: str) -> dict[Point, date]:
    return {Point(p): date.fromisoformat(d) for p, d in _days(data)[kind].items()}


def _single_day(data: dict, kind: str) -> date | None:
    raw = _days(data).get(kind)
    return date.fromisoformat(raw) if raw else None


def _min_day(data: dict, step: Target) -> date:
    """Самая ранняя допустимая дата шага — те же правила, что в validate_schedule."""
    if step.kind == "dropoff":
        return min_dropoff_date()
    if step.kind == "issue":
        return max(_point_days(data, "dropoff").values()) + timedelta(days=1)
    if step.kind == "return":
        return _single_day(data, "issue")
    return _single_day(data, "return") + timedelta(days=1)


def _previous_point_day(data: dict, step_idx: int) -> date | None:
    """Дата последнего заполненного пункта того же типа — для кнопки «Как у предыдущего»."""
    step = STEPS[step_idx]
    days = _point_days(data, step.kind)
    for prev in reversed(STEPS[:step_idx]):
        if prev.kind == step.kind and prev.point in days:
            return days[prev.point]
    return None


def _can_skip(data: dict, step_idx: int) -> bool:
    """Пункт можно пропустить, если у типа останется хотя бы один заполненный пункт."""
    step = STEPS[step_idx]
    if step.point is None:
        return False
    is_last_of_kind = all(s.kind != step.kind for s in STEPS[step_idx + 1:])
    return not is_last_of_kind or bool(_days(data)[step.kind])


def _schedule_text(data: dict) -> str:
    def label(day: date | None) -> str:
        return Window(day).label() if day else "—"

    return format_schedule(
        dropoffs={p: label(d) for p, d in _point_days(data, "dropoff").items()},
        issue=label(_single_day(data, "issue")),
        return_=label(_single_day(data, "return")),
        pickups={p: label(d) for p, d in _point_days(data, "pickup").items()},
    )


def _day_kb(data: dict, step_idx: int, shown: date | None = None) -> InlineKeyboardMarkup:
    step = STEPS[step_idx]
    min_day = _min_day(data, step)
    shown = max(shown or min_day, min_day.replace(day=1))
    extra = []
    if step.point is not None:
        same = _previous_point_day(data, step_idx)
        extra = point_step_rows(
            same_label=f"{same:%d.%m.%Y}" if same and same >= min_day else None,
            can_skip=_can_skip(data, step_idx),
        )
    return calendar_kb(
        kind="ev",
        year=shown.year,
        month=shown.month,
        min_date=min_day,
        cancel_callback="ad:cancel",
        extra_rows=extra,
    )


def _day_prompt(data: dict, step_idx: int) -> str:
    step = STEPS[step_idx]
    filled = f"{_schedule_text(data)}\n\n" if step_idx else ""
    return (
        f"<b>{escape(data['name'])}</b>, {data['price']} ₽\n"
        f"Время везде {DEFAULT_STARTS_AT:%H:%M}–{DEFAULT_ENDS_AT:%H:%M}, "
        "поменять можно будет в редактировании.\n\n"
        f"{filled}"
        f"Шаг {step_idx + 1}/{len(STEPS)}. {step.title}\n"
        "Выбери дату:"
    )


async def _save_day(state: FSMContext, day: date | None) -> None:
    """Сохраняет дату текущего шага (None — пункт пропущен) и переходит к следующему."""
    data = await state.get_data()
    step = STEPS[data["step"]]
    days = _days(data)
    if step.point is not None:
        if day is not None:
            days[step.kind][step.point.value] = day.isoformat()
    else:
        days[step.kind] = day.isoformat()
    await state.update_data(days=days, step=data["step"] + 1)


async def _show_step(message: Message, state: FSMContext, *, edit: bool) -> None:
    """Показывает текущий шаг или, если шаги кончились, сводку с кнопкой «Создать»."""
    data = await state.get_data()
    if data["step"] < len(STEPS):
        await state.set_state(AdminCreateForm.day)
        text = _day_prompt(data, data["step"])
        kb = _day_kb(data, data["step"])
    else:
        await state.set_state(AdminCreateForm.confirm)
        text = (
            f"<b>{escape(data['name'])}</b>, {data['price']} ₽\n\n"
            f"{_schedule_text(data)}\n\n"
            "Событие создастся с <b>закрытой</b> регистрацией — открой её в карточке, "
            "когда проверишь время.\nСоздать?"
        )
        kb = admin_confirm_kb()
    if edit:
        await message.edit_text(text, reply_markup=kb)
    else:
        await message.answer(text, reply_markup=kb)


# --- меню ---

@admin_router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "Админка.",
        reply_markup=admin_menu_kb(),
    )


@admin_router.callback_query(F.data == "ad:close")
async def cb_close(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await callback.message.edit_text("Админка закрыта.")


@admin_router.callback_query(F.data == "ad:cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await callback.message.edit_text(
        "Отменено.",
        reply_markup=admin_menu_kb(),
    )


# --- этап 1: название и цена ---

@admin_router.callback_query(F.data == "ad:custom")
async def cb_custom(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await state.set_state(AdminCreateForm.name)
    await callback.message.answer(
        "Введи название мероприятия:",
        reply_markup=admin_cancel_kb(),
    )


@admin_router.message(AdminCreateForm.name, F.text)
async def msg_name(message: Message, state: FSMContext) -> None:
    try:
        name = normalize_name(message.text or "")
    except AdminError as exc:
        await message.answer(f"{exc} Ещё раз:", reply_markup=admin_cancel_kb())
        return
    await state.update_data(name=name)
    await state.set_state(AdminCreateForm.price)
    await message.answer(
        "Введи цену в рублях (например 9900):",
        reply_markup=admin_cancel_kb(),
    )


@admin_router.message(AdminCreateForm.price, F.text)
async def msg_price(message: Message, state: FSMContext) -> None:
    try:
        price = parse_price(message.text or "")
    except AdminError as exc:
        await message.answer(str(exc), reply_markup=admin_cancel_kb())
        return

    await state.update_data(price=str(price), step=0, days={"dropoff": {}, "pickup": {}})
    await _show_step(message, state, edit=False)


# --- этап 2: даты ---

@admin_router.callback_query(F.data == CALENDAR_IGNORE)
async def cb_calendar_ignore(callback: CallbackQuery) -> None:
    await callback.answer()


@admin_router.callback_query(AdminCreateForm.day, F.data.startswith("cal:ev:m:"))
async def cb_calendar_month(callback: CallbackQuery, state: FSMContext) -> None:
    shown = date.fromisoformat(f"{callback.data.split(':')[-1]}-01")
    data = await state.get_data()
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=_day_kb(data, data["step"], shown))


@admin_router.callback_query(AdminCreateForm.day, F.data.startswith("cal:ev:d:"))
async def cb_pick_day(callback: CallbackQuery, state: FSMContext) -> None:
    day = date.fromisoformat(callback.data.split(":")[-1])
    data = await state.get_data()
    if day < _min_day(data, STEPS[data["step"]]):
        await callback.answer("Эта дата недоступна.", show_alert=True)
        return
    await callback.answer()
    await _save_day(state, day)
    await _show_step(callback.message, state, edit=True)


@admin_router.callback_query(AdminCreateForm.day, F.data == "ad:same")
async def cb_same(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    day = _previous_point_day(data, data["step"])
    if day is None or day < _min_day(data, STEPS[data["step"]]):
        await callback.answer("Нет подходящего предыдущего пункта.", show_alert=True)
        return
    await callback.answer()
    await _save_day(state, day)
    await _show_step(callback.message, state, edit=True)


@admin_router.callback_query(AdminCreateForm.day, F.data == "ad:skip")
async def cb_skip(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if not _can_skip(data, data["step"]):
        await callback.answer("Нужен хотя бы один работающий пункт.", show_alert=True)
        return
    await callback.answer()
    await _save_day(state, None)
    await _show_step(callback.message, state, edit=True)


@admin_router.callback_query(AdminCreateForm.confirm, F.data == "ad:create")
async def cb_create(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    await callback.answer()
    try:
        async for db in get_session():
            event = await create_event(
                db,
                name=data["name"],
                price=Decimal(data["price"]),
                dropoffs=_point_days(data, "dropoff"),
                issue=_single_day(data, "issue"),
                return_=_single_day(data, "return"),
                pickups=_point_days(data, "pickup"),
            )
    except AdminError as exc:
        await callback.message.edit_text(str(exc), reply_markup=admin_menu_kb())
        return
    except Exception:
        logger.exception("admin create event failed")
        await callback.message.edit_text("Не удалось создать событие.", reply_markup=admin_menu_kb())
        return

    await render_card(callback.message, event.id, edit=True)


@admin_router.message(AdminCreateForm.name)
@admin_router.message(AdminCreateForm.price)
async def msg_unexpected(message: Message) -> None:
    await message.answer("Пришли текстом или нажми «Отмена».", reply_markup=admin_cancel_kb())


@admin_router.message(AdminCreateForm.day)
@admin_router.message(AdminCreateForm.confirm)
async def msg_expect_buttons(message: Message) -> None:
    await message.answer("Используй кнопки выше или нажми «Отмена».")
