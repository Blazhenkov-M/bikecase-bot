from __future__ import annotations

import logging
from html import escape
from datetime import date
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Event, Point
from app.handlers.admin.filters import is_admin
from app.handlers.user.start import CLIENT_MENU_TEXT
from app.keyboards.booking import confirm_kb, consent_kb, days_kb, points_kb, step_kb
from app.keyboards.start import client_menu_kb
from app.services.applications import (
    ApplicationError,
    DayUnavailableError,
    create_application,
    format_application,
    free_days,
    get_active_application,
    get_open_registration_event,
    give_consent,
    has_consent,
    needs_day,
    normalize_field,
)
from app.services.user import add_or_update_user

logger = logging.getLogger(__name__)
router = Router()

DOCUMENTS_DIR = Path(__file__).resolve().parents[3] / "documents"
CONSENT_DOCUMENTS = ("Согласие_на_обработку_ПДн_bikecase_transfer_bot.pdf", "Политика_конфиденциальности_bikecase_transfer_bot.pdf")
# file_id уже загруженных PDF, чтобы не грузить файлы заново каждый раз
_document_ids: dict[str, str] = {}


class BookingForm(StatesGroup):
    consent = State()
    first_name = State()
    last_name = State()
    phone = State()
    bicycle_brand = State()
    bicycle_color = State()
    dropoff_point = State()
    dropoff_date = State()
    pickup_point = State()
    pickup_date = State()
    confirm = State()


# Порядок шагов анкеты (согласие — до анкеты, в «Назад» не участвует).
# Шаги *_date показываются только если выбрано Крылатское.
STEPS: list[State] = [
    BookingForm.first_name,
    BookingForm.last_name,
    BookingForm.phone,
    BookingForm.bicycle_brand,
    BookingForm.bicycle_color,
    BookingForm.dropoff_point,
    BookingForm.dropoff_date,
    BookingForm.pickup_point,
    BookingForm.pickup_date,
    BookingForm.confirm,
]
TEXT_STEPS = STEPS[:5]
POINT_STEPS = (BookingForm.dropoff_point, BookingForm.pickup_point)
DATE_STEPS = (BookingForm.dropoff_date, BookingForm.pickup_date)

POINT_PROMPTS = {
    "dropoff": "Где сдадите велосипед?",
    "pickup": "Где заберёте велосипед после мероприятия?",
}
DAY_PROMPTS = {
    "dropoff": "В какой день привезёте велосипед в Крылатское?",
    "pickup": "В какой день заберёте велосипед в Крылатском?",
}
NO_PLACES = "В Крылатском свободных мест не осталось."

PROMPTS = {
    "first_name": "Введите имя участника:",
    "last_name": "Введите фамилию участника:",
    "phone": "Введите номер телефона для связи:",
    "bicycle_brand": "Введите марку велосипеда (например, Canyon):",
    "bicycle_color": "Введите цвет велосипеда:",
}


def _field(step: State) -> str:
    return step.state.split(":")[1]


async def _step_screen(state: FSMContext, session: AsyncSession) -> tuple[str, InlineKeyboardMarkup]:
    current = await state.get_state()
    step = next(s for s in STEPS if s.state == current)
    data = await state.get_data()
    fields = data["fields"]

    if step in TEXT_STEPS:
        field = _field(step)
        text = PROMPTS[field]
        if field in fields:
            text += f"\nСейчас: <b>{escape(fields[field])}</b>"
        return text, step_kb(back=step != STEPS[0])

    event = await session.get(Event, data["event_id"])
    if step == BookingForm.confirm:
        return f"Проверьте заявку:\n\n{format_application(fields, event)}", confirm_kb()

    kind = _field(step).split("_")[0]
    days = await free_days(session, event, kind)
    if step in POINT_STEPS:
        text = f"{POINT_PROMPTS[kind]}\nВ мастерские — в любой день из указанных, в Крылатское — в выбранный день."
        if not days:
            text += f"\n\n{NO_PLACES}"
        return text, points_kb(event, kind, hidden=() if days else (Point.krylatskoe,))
    if not days:
        return f"{NO_PLACES} Вернитесь назад и выберите другую точку.", days_kb([])
    return DAY_PROMPTS[kind], days_kb(days)


async def _go(state: FSMContext, session: AsyncSession, step: State) -> tuple[str, InlineKeyboardMarkup]:
    await state.set_state(step)
    return await _step_screen(state, session)


async def _neighbour_step(state: FSMContext, delta: int) -> State:
    """Следующий (delta=1) или предыдущий (-1) шаг; выбор дня пропускается, если точка — не Крылатское."""
    current = await state.get_state()
    fields = (await state.get_data())["fields"]
    idx = next(i for i, s in enumerate(STEPS) if s.state == current) + delta
    while STEPS[idx] in DATE_STEPS and not needs_day(fields[_field(STEPS[idx]).replace("_date", "_point")]):
        idx += delta
    return STEPS[idx]


async def _next_step(state: FSMContext) -> State:
    return await _neighbour_step(state, 1)


async def _send_consent_documents(message: Message) -> None:
    for name in CONSENT_DOCUMENTS:
        document = _document_ids.get(name) or FSInputFile(DOCUMENTS_DIR / name)
        sent = await message.answer_document(document)
        _document_ids[name] = sent.document.file_id


async def _back_to_menu(callback: CallbackQuery, state: FSMContext, text: str) -> None:
    await state.clear()
    await callback.message.edit_text(
        text,
        reply_markup=client_menu_kb(is_admin=is_admin(callback.from_user.id)),
    )


# --- старт и согласие ---

@router.callback_query(F.data == "bk:start")
async def cb_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    user = callback.from_user
    try:
        event = await get_open_registration_event(session)
    except ApplicationError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    if await get_active_application(session, user.id, event.id):
        await callback.answer("У вас уже есть заявка на это событие — она в «Мои заявки».", show_alert=True)
        return

    await callback.answer()
    # Пользователь мог не нажимать /start после сброса базы — без записи в users заявку не сохранить.
    await add_or_update_user(
        tg_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        language_code=user.language_code,
        is_premium=user.is_premium,
        session=session,
    )
    await state.clear()
    await state.update_data(event_id=event.id, fields={})

    if await has_consent(session, user.id):
        text, kb = await _go(state, session, STEPS[0])
        await callback.message.edit_text(text, reply_markup=kb)
        return

    await state.set_state(BookingForm.consent)
    await callback.message.edit_text("Перед оформлением заявки ознакомьтесь с документами:")
    try:
        await _send_consent_documents(callback.message)
    except Exception:
        logger.exception("failed to send consent documents")
    await callback.message.answer(
        "Нажимая «Согласен», вы даёте согласие на обработку персональных данных "
        "в соответствии с документами выше.",
        reply_markup=consent_kb(),
    )


@router.callback_query(BookingForm.consent, F.data == "bk:consent")
async def cb_consent(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await give_consent(session, callback.from_user.id)
    await callback.answer("Спасибо!")
    text, kb = await _go(state, session, STEPS[0])
    await callback.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data == "bk:cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await _back_to_menu(callback, state, f"Оформление отменено.\n\n{CLIENT_MENU_TEXT}")


@router.callback_query(StateFilter(*STEPS[1:]), F.data == "bk:back")
async def cb_back(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await callback.answer()
    text, kb = await _go(state, session, await _neighbour_step(state, -1))
    await callback.message.edit_text(text, reply_markup=kb)


# --- анкета ---

@router.message(StateFilter(*TEXT_STEPS), F.text)
async def msg_text_step(message: Message, state: FSMContext, session: AsyncSession) -> None:
    current = await state.get_state()
    field = current.split(":")[1]
    data = await state.get_data()
    try:
        value = normalize_field(field, message.text)
    except ApplicationError as exc:
        await message.answer(f"{exc}\n\n{PROMPTS[field]}", reply_markup=step_kb(back=field != "first_name"))
        return
    await state.update_data(fields={**data["fields"], field: value})
    text, kb = await _go(state, session, await _next_step(state))
    await message.answer(text, reply_markup=kb)


@router.callback_query(StateFilter(*POINT_STEPS), F.data.startswith("bk:pt:"))
async def cb_point(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    field = (await state.get_state()).split(":")[1]
    kind = field.split("_")[0]
    data = await state.get_data()
    point = callback.data.split(":")[2]
    # День относится к точке: при её смене выбирается заново.
    fields = {**data["fields"], field: point}
    if point != data["fields"].get(field) or not needs_day(point):
        fields.pop(f"{kind}_date", None)
    await state.update_data(fields=fields)
    await callback.answer()
    text, kb = await _go(state, session, await _next_step(state))
    await callback.message.edit_text(text, reply_markup=kb)


@router.callback_query(StateFilter(*DATE_STEPS), F.data.startswith("bk:day:"))
async def cb_day(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    field = (await state.get_state()).split(":")[1]
    kind = field.split("_")[0]
    data = await state.get_data()
    day = date.fromisoformat(callback.data.split(":")[2])
    event = await session.get(Event, data["event_id"])
    if day not in await free_days(session, event, kind):
        # Пока клиент думал, день заняли — показываем актуальный список.
        await callback.answer("На этот день мест уже нет — выберите другой.", show_alert=True)
        text, kb = await _step_screen(state, session)
        await callback.message.edit_text(text, reply_markup=kb)
        return
    await state.update_data(fields={**data["fields"], field: day.isoformat()})
    await callback.answer()
    text, kb = await _go(state, session, await _next_step(state))
    await callback.message.edit_text(text, reply_markup=kb)


@router.callback_query(BookingForm.confirm, F.data == "bk:confirm")
async def cb_confirm(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    try:
        application = await create_application(session, callback.from_user.id, data["event_id"], data["fields"])
    except DayUnavailableError as exc:
        # Анкету не теряем: возвращаем к выбору дня, который успели занять.
        await session.rollback()
        await callback.answer(str(exc), show_alert=True)
        fields = {k: v for k, v in data["fields"].items() if k != f"{exc.kind}_date"}
        await state.update_data(fields=fields)
        text, kb = await _go(state, session, getattr(BookingForm, f"{exc.kind}_date"))
        await callback.message.edit_text(text, reply_markup=kb)
        return
    except ApplicationError as exc:
        await callback.answer(str(exc), show_alert=True)
        await _back_to_menu(callback, state, CLIENT_MENU_TEXT)
        return
    except Exception:
        logger.exception("create application failed")
        await callback.answer("Не удалось сохранить заявку, попробуйте позже.", show_alert=True)
        return

    await callback.answer("Заявка отправлена")
    event = await session.get(Event, data["event_id"])
    await state.clear()
    await callback.message.edit_text(
        f"Заявка №{application.id} принята ✅\n\n{format_application(data['fields'], event)}\n\n"
        "Посмотреть, изменить или отменить её можно в «Мои заявки».",
    )
    await callback.message.answer(
        CLIENT_MENU_TEXT,
        reply_markup=client_menu_kb(is_admin=is_admin(callback.from_user.id)),
    )


# --- неожиданный ввод ---

@router.message(StateFilter(*TEXT_STEPS))
async def msg_expect_text(message: Message) -> None:
    await message.answer("Пришлите ответ текстом или нажмите «Отмена».")


@router.message(StateFilter(BookingForm.consent, *POINT_STEPS, *DATE_STEPS, BookingForm.confirm))
async def msg_expect_buttons(message: Message) -> None:
    await message.answer("Используйте кнопки выше или нажмите «Отмена».")
