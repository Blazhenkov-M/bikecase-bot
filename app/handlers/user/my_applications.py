from __future__ import annotations

import logging
from datetime import date

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Point
from app.keyboards.booking import days_kb, points_kb
from app.keyboards.my_applications import (
    application_card_kb,
    applications_list_kb,
    back_to_edit_rows,
    cancel_confirm_kb,
    edit_fields_kb,
)
from app.services.applications import (
    TEXT_FIELDS,
    ApplicationError,
    DayUnavailableError,
    application_fields,
    cancel_application,
    format_application,
    free_days,
    get_editable_application,
    get_user_application,
    is_editable,
    list_user_applications,
    needs_day,
    update_application_field,
    update_application_point,
)

logger = logging.getLogger(__name__)
router = Router()


class MyApplicationForm(StatesGroup):
    text = State()
    point = State()
    day = State()


async def _card(session: AsyncSession, user_id: int, application_id: int) -> tuple[str, InlineKeyboardMarkup]:
    application = await get_user_application(session, user_id, application_id)
    editable = is_editable(application)
    text = f"Заявка №{application.id}\n\n{format_application(application_fields(application), application.event)}"
    if not editable:
        text += "\n\nРегистрация закрыта — изменить или отменить заявку можно через поддержку."
    return text, application_card_kb(application.id, editable=editable)


def _ids(callback: CallbackQuery) -> list[str]:
    """my:<action>:<id>[:<field>] → [id, field?]"""
    return callback.data.split(":")[2:]


# --- список и карточка ---

@router.callback_query(F.data == "my:list")
async def cb_list(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    await callback.answer()
    applications = await list_user_applications(session, callback.from_user.id)
    text = "Ваши заявки:" if applications else "У вас нет активных заявок."
    await callback.message.edit_text(text, reply_markup=applications_list_kb(applications))


@router.callback_query(F.data.regexp(r"^my:app:\d+$"))
async def cb_card(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    try:
        text, kb = await _card(session, callback.from_user.id, int(_ids(callback)[0]))
    except ApplicationError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text(text, reply_markup=kb)


# --- отмена ---

@router.callback_query(F.data.regexp(r"^my:cancel:\d+$"))
async def cb_cancel(callback: CallbackQuery, session: AsyncSession) -> None:
    application_id = int(_ids(callback)[0])
    try:
        await get_editable_application(session, callback.from_user.id, application_id)
    except ApplicationError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text(
        f"Отменить заявку №{application_id}?",
        reply_markup=cancel_confirm_kb(application_id),
    )


@router.callback_query(F.data.regexp(r"^my:cancel_ok:\d+$"))
async def cb_cancel_ok(callback: CallbackQuery, session: AsyncSession) -> None:
    application_id = int(_ids(callback)[0])
    try:
        await cancel_application(session, callback.from_user.id, application_id)
    except ApplicationError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer("Заявка отменена")
    applications = await list_user_applications(session, callback.from_user.id)
    await callback.message.edit_text(
        f"Заявка №{application_id} отменена. При желании можно оформить новую.",
        reply_markup=applications_list_kb(applications),
    )


# --- редактирование ---

@router.callback_query(F.data.regexp(r"^my:ed:\d+$"))
async def cb_edit_menu(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    application_id = int(_ids(callback)[0])
    try:
        await get_editable_application(session, callback.from_user.id, application_id)
    except ApplicationError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text("Что изменить?", reply_markup=edit_fields_kb(application_id))


@router.callback_query(
    F.data.regexp(r"^my:ed:\d+:(first_name|last_name|phone|bicycle_brand|bicycle_color|dropoff_point|pickup_point)$")
)
async def cb_edit_field(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    raw_id, field = _ids(callback)
    application_id = int(raw_id)
    try:
        application = await get_editable_application(session, callback.from_user.id, application_id)
    except ApplicationError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()
    await state.update_data(application_id=application_id, field=field)
    back = InlineKeyboardMarkup(inline_keyboard=back_to_edit_rows(application_id))

    if field in TEXT_FIELDS:
        await state.set_state(MyApplicationForm.text)
        label = TEXT_FIELDS[field][0]
        await callback.message.edit_text(f"{label}: введите новое значение.", reply_markup=back)
        return

    await state.set_state(MyApplicationForm.point)
    kind = field.split("_")[0]
    prompt = "Выберите новую точку сдачи:" if kind == "dropoff" else "Выберите новую точку получения:"
    days = await free_days(session, application.event, kind, exclude_application_id=application_id)
    if not days:
        prompt += "\n\nВ Крылатском свободных мест не осталось."
    await callback.message.edit_text(
        prompt,
        reply_markup=points_kb(
            application.event,
            kind,
            back_to_edit_rows(application_id),
            hidden=() if days else (Point.krylatskoe,),
        ),
    )


async def _saved_card(
    session: AsyncSession, state: FSMContext, user_id: int, application_id: int
) -> tuple[str, InlineKeyboardMarkup]:
    await state.clear()
    text, kb = await _card(session, user_id, application_id)
    return f"Сохранено ✅\n\n{text}", kb


async def _save(session: AsyncSession, state: FSMContext, user_id: int, raw: str) -> tuple[str, InlineKeyboardMarkup]:
    data = await state.get_data()
    await update_application_field(session, user_id, data["application_id"], data["field"], raw)
    return await _saved_card(session, state, user_id, data["application_id"])


async def _save_point(
    session: AsyncSession, state: FSMContext, user_id: int, point: Point, day: date | None
) -> tuple[str, InlineKeyboardMarkup]:
    data = await state.get_data()
    kind = data["field"].split("_")[0]
    await update_application_point(session, user_id, data["application_id"], kind, point, day)
    return await _saved_card(session, state, user_id, data["application_id"])


async def _days_screen(
    session: AsyncSession, user_id: int, application_id: int, kind: str
) -> tuple[str, InlineKeyboardMarkup]:
    application = await get_editable_application(session, user_id, application_id)
    days = await free_days(session, application.event, kind, exclude_application_id=application_id)
    nav = back_to_edit_rows(application_id)
    if not days:
        return "В Крылатском свободных мест не осталось. Вернитесь назад и выберите другую точку.", days_kb([], nav)
    prompt = "В какой день привезёте велосипед в Крылатское?" if kind == "dropoff" else "В какой день заберёте велосипед в Крылатском?"
    return prompt, days_kb(days, nav)


@router.message(MyApplicationForm.text, F.text)
async def msg_edit_text(message: Message, state: FSMContext, session: AsyncSession) -> None:
    try:
        text, kb = await _save(session, state, message.from_user.id, message.text)
    except ApplicationError as exc:
        application_id = (await state.get_data())["application_id"]
        await message.answer(
            f"{exc}\n\nВведите ещё раз:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=back_to_edit_rows(application_id)),
        )
        return
    await message.answer(text, reply_markup=kb)


@router.callback_query(MyApplicationForm.point, F.data.startswith("bk:pt:"))
async def cb_edit_point(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    point = Point(callback.data.split(":")[2])
    data = await state.get_data()
    try:
        if needs_day(point):
            # Точка сохранится вместе с днём — на следующем шаге.
            text, kb = await _days_screen(
                session, callback.from_user.id, data["application_id"], data["field"].split("_")[0]
            )
            await state.set_state(MyApplicationForm.day)
        else:
            text, kb = await _save_point(session, state, callback.from_user.id, point, None)
    except ApplicationError as exc:
        await state.clear()
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text(text, reply_markup=kb)


@router.callback_query(MyApplicationForm.day, F.data.startswith("bk:day:"))
async def cb_edit_day(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    day = date.fromisoformat(callback.data.split(":")[2])
    data = await state.get_data()
    user_id = callback.from_user.id
    try:
        text, kb = await _save_point(session, state, user_id, Point.krylatskoe, day)
    except DayUnavailableError as exc:
        # День успели занять — показываем актуальный список.
        await session.rollback()
        await callback.answer(str(exc), show_alert=True)
        try:
            text, kb = await _days_screen(session, user_id, data["application_id"], data["field"].split("_")[0])
        except ApplicationError:
            await state.clear()
            return
        await callback.message.edit_text(text, reply_markup=kb)
        return
    except ApplicationError as exc:
        await state.clear()
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text(text, reply_markup=kb)


# --- неожиданный ввод ---

@router.message(MyApplicationForm.text)
async def msg_expect_text(message: Message) -> None:
    await message.answer("Пришлите новое значение текстом или нажмите «Назад».")


@router.message(MyApplicationForm.point)
@router.message(MyApplicationForm.day)
async def msg_expect_buttons(message: Message) -> None:
    await message.answer("Используйте кнопки выше.")
