from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.types import User as TgUser

from app.database.database import get_session
from app.database.models import SlotType
from app.services.user import add_or_update_user
from app.keyboards.booking import (
    cancel_only_kb,
    confirm_kb,
    events_kb,
    prestart_kb,
    slots_kb,
    text_nav_kb,
)
from app.services.booking import (
    BookingDraft,
    BookingError,
    build_review_text,
    create_booking,
    get_open_event,
    get_slot_for_event,
    list_available_slots,
    list_open_events,
    normalize_text,
)

logger = logging.getLogger(__name__)
router = Router()


class BookingForm(StatesGroup):
    choosing_event = State()
    first_name = State()
    last_name = State()
    bicycle_brand = State()
    bicycle_color = State()
    dropoff_slot = State()
    pickup_slot = State()
    prestart_service = State()
    confirming = State()


async def _clear_state(state: FSMContext) -> None:
    await state.clear()


async def start_booking_flow(message: Message, state: FSMContext, user: TgUser | None) -> None:
    # user передаётся явно: у callback.message from_user — это сам бот
    await _clear_state(state)
    if user is None:
        await message.answer("Не удалось определить пользователя.")
        return

    try:
        async for db in get_session():
            await add_or_update_user(
                tg_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
                language_code=user.language_code,
                is_premium=user.is_premium,
                session=db,
            )
            events = await list_open_events(db)
    except Exception:
        logger.exception("Failed to load open events")
        await message.answer("Не удалось загрузить мероприятия. Попробуйте позже.")
        return

    if not events:
        await message.answer("Сейчас нет мероприятий с открытой регистрацией.")
        return

    await state.set_state(BookingForm.choosing_event)
    await message.answer(
        "Выберите мероприятие:",
        reply_markup=events_kb(events),
    )


@router.callback_query(F.data == "bk:start")
async def cb_start_booking(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await start_booking_flow(callback.message, state, callback.from_user)


@router.callback_query(F.data == "bk:cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await _clear_state(state)
    await callback.answer()
    await callback.message.edit_text("Оформление заявки отменено.")


@router.callback_query(F.data.startswith("bk:back:"))
async def cb_back(callback: CallbackQuery, state: FSMContext) -> None:
    target = callback.data.split(":")[-1]
    await callback.answer()

    data = await state.get_data()
    event_id = data.get("event_id")

    try:
        if target == "event":
            async for db in get_session():
                events = await list_open_events(db)
            await state.set_state(BookingForm.choosing_event)
            await callback.message.edit_text(
                "Выберите мероприятие:",
                reply_markup=events_kb(events),
            )
            return

        if target == "first_name":
            await state.set_state(BookingForm.first_name)
            await callback.message.edit_text(
                "Введите имя участника:",
                reply_markup=text_nav_kb(back_to="event"),
            )
            return

        if target == "last_name":
            await state.set_state(BookingForm.last_name)
            await callback.message.edit_text(
                "Введите фамилию участника:",
                reply_markup=text_nav_kb(back_to="first_name"),
            )
            return

        if target == "brand":
            await state.set_state(BookingForm.bicycle_brand)
            await callback.message.edit_text(
                "Введите марку велосипеда:",
                reply_markup=text_nav_kb(back_to="last_name"),
            )
            return

        if target == "color":
            await state.set_state(BookingForm.bicycle_color)
            await callback.message.edit_text(
                "Введите цвет велосипеда:",
                reply_markup=text_nav_kb(back_to="brand"),
            )
            return

        if target == "dropoff" and event_id is not None:
            async for db in get_session():
                slots = await list_available_slots(db, event_id, SlotType.dropoff)
            await state.set_state(BookingForm.dropoff_slot)
            if not slots:
                await callback.message.edit_text(
                    "Нет доступных слотов сдачи. Выберите другое мероприятие.",
                    reply_markup=text_nav_kb(back_to="event"),
                )
                return
            await callback.message.edit_text(
                "Выберите пункт и время сдачи велосипеда в Москве:",
                reply_markup=slots_kb(slots, kind="dropoff", back_to="color"),
            )
            return

        if target == "pickup" and event_id is not None:
            async for db in get_session():
                slots = await list_available_slots(db, event_id, SlotType.pickup)
            await state.set_state(BookingForm.pickup_slot)
            if not slots:
                await callback.message.edit_text(
                    "Нет доступных слотов получения.",
                    reply_markup=text_nav_kb(back_to="dropoff"),
                )
                return
            await callback.message.edit_text(
                "Выберите пункт и время возврата велосипеда в Москве:",
                reply_markup=slots_kb(slots, kind="pickup", back_to="dropoff"),
            )
            return

        if target == "prestart":
            await state.set_state(BookingForm.prestart_service)
            await callback.message.edit_text(
                "Нужно ли предстартовое ТО велосипеда?",
                reply_markup=prestart_kb(),
            )
            return

        await callback.message.answer("Некуда возвращаться. Начните оформление заново.")
        await _clear_state(state)
    except BookingError as exc:
        await _clear_state(state)
        await callback.message.answer(str(exc))
    except Exception:
        logger.exception("Back navigation failed")
        await _clear_state(state)
        await callback.message.answer("Произошла ошибка. Начните оформление заново.")


@router.callback_query(BookingForm.choosing_event, F.data.startswith("bk:event:"))
async def cb_choose_event(callback: CallbackQuery, state: FSMContext) -> None:
    event_id = int(callback.data.split(":")[-1])
    try:
        async for db in get_session():
            event = await get_open_event(db, event_id)
            event_name = event.name
            await state.update_data(event_id=event.id, event_name=event_name)
    except BookingError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    except Exception:
        logger.exception("Failed to choose event")
        await callback.answer("Ошибка загрузки мероприятия", show_alert=True)
        return

    await callback.answer()
    await state.set_state(BookingForm.first_name)
    await callback.message.edit_text(
        f"Мероприятие: <b>{event_name}</b>\n\nВведите имя участника:",
        reply_markup=text_nav_kb(back_to="event"),
    )


@router.message(BookingForm.first_name, F.text)
async def msg_first_name(message: Message, state: FSMContext) -> None:
    try:
        value = normalize_text(message.text or "", field="Имя", max_len=64)
    except BookingError as exc:
        await message.answer(str(exc), reply_markup=text_nav_kb(back_to="event"))
        return

    await state.update_data(participant_first_name=value)
    await state.set_state(BookingForm.last_name)
    await message.answer(
        "Введите фамилию участника:",
        reply_markup=text_nav_kb(back_to="first_name"),
    )


@router.message(BookingForm.last_name, F.text)
async def msg_last_name(message: Message, state: FSMContext) -> None:
    try:
        value = normalize_text(message.text or "", field="Фамилия", max_len=64)
    except BookingError as exc:
        await message.answer(str(exc), reply_markup=text_nav_kb(back_to="first_name"))
        return

    await state.update_data(participant_last_name=value)
    await state.set_state(BookingForm.bicycle_brand)
    await message.answer(
        "Введите марку велосипеда:",
        reply_markup=text_nav_kb(back_to="last_name"),
    )


@router.message(BookingForm.bicycle_brand, F.text)
async def msg_brand(message: Message, state: FSMContext) -> None:
    try:
        value = normalize_text(message.text or "", field="Марка", max_len=128)
    except BookingError as exc:
        await message.answer(str(exc), reply_markup=text_nav_kb(back_to="last_name"))
        return

    await state.update_data(bicycle_brand=value)
    await state.set_state(BookingForm.bicycle_color)
    await message.answer(
        "Введите цвет велосипеда:",
        reply_markup=text_nav_kb(back_to="brand"),
    )


@router.message(BookingForm.bicycle_color, F.text)
async def msg_color(message: Message, state: FSMContext) -> None:
    try:
        value = normalize_text(message.text or "", field="Цвет", max_len=64)
    except BookingError as exc:
        await message.answer(str(exc), reply_markup=text_nav_kb(back_to="brand"))
        return

    data = await state.get_data()
    event_id = data["event_id"]
    await state.update_data(bicycle_color=value)

    try:
        async for db in get_session():
            slots = await list_available_slots(db, event_id, SlotType.dropoff)
    except BookingError as exc:
        await _clear_state(state)
        await message.answer(str(exc))
        return
    except Exception:
        logger.exception("Failed to load dropoff slots")
        await _clear_state(state)
        await message.answer("Не удалось загрузить слоты. Начните оформление заново.")
        return

    await state.set_state(BookingForm.dropoff_slot)
    if not slots:
        await message.answer(
            "Нет доступных слотов сдачи для этого мероприятия.",
            reply_markup=text_nav_kb(back_to="event"),
        )
        return

    await message.answer(
        "Выберите пункт и время сдачи велосипеда в Москве:",
        reply_markup=slots_kb(slots, kind="dropoff", back_to="color"),
    )


@router.callback_query(BookingForm.dropoff_slot, F.data.startswith("bk:slot:dropoff:"))
async def cb_dropoff(callback: CallbackQuery, state: FSMContext) -> None:
    slot_id = int(callback.data.split(":")[-1])
    data = await state.get_data()
    event_id = data["event_id"]

    try:
        async for db in get_session():
            await get_slot_for_event(
                db,
                event_id=event_id,
                slot_id=slot_id,
                slot_type=SlotType.dropoff,
            )
            slots = await list_available_slots(db, event_id, SlotType.pickup)
    except BookingError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    except Exception:
        logger.exception("Failed to select dropoff slot")
        await callback.answer("Ошибка выбора слота", show_alert=True)
        return

    await state.update_data(dropoff_slot_id=slot_id)
    await callback.answer()
    await state.set_state(BookingForm.pickup_slot)

    if not slots:
        await callback.message.edit_text(
            "Нет доступных слотов получения.",
            reply_markup=text_nav_kb(back_to="dropoff"),
        )
        return

    await callback.message.edit_text(
        "Выберите пункт и время возврата велосипеда в Москве:",
        reply_markup=slots_kb(slots, kind="pickup", back_to="dropoff"),
    )


@router.callback_query(BookingForm.pickup_slot, F.data.startswith("bk:slot:pickup:"))
async def cb_pickup(callback: CallbackQuery, state: FSMContext) -> None:
    slot_id = int(callback.data.split(":")[-1])
    data = await state.get_data()
    event_id = data["event_id"]

    try:
        async for db in get_session():
            await get_slot_for_event(
                db,
                event_id=event_id,
                slot_id=slot_id,
                slot_type=SlotType.pickup,
            )
    except BookingError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    except Exception:
        logger.exception("Failed to select pickup slot")
        await callback.answer("Ошибка выбора слота", show_alert=True)
        return

    await state.update_data(pickup_slot_id=slot_id)
    await callback.answer()
    await state.set_state(BookingForm.prestart_service)
    await callback.message.edit_text(
        "Нужно ли предстартовое ТО велосипеда?",
        reply_markup=prestart_kb(),
    )


@router.callback_query(BookingForm.prestart_service, F.data.startswith("bk:prestart:"))
async def cb_prestart(callback: CallbackQuery, state: FSMContext) -> None:
    choice = callback.data.split(":")[-1]
    prestart = choice == "1"
    await state.update_data(prestart_service=prestart)

    data = await state.get_data()
    try:
        async for db in get_session():
            event = await get_open_event(db, data["event_id"])
            dropoff = await get_slot_for_event(
                db,
                event_id=event.id,
                slot_id=data["dropoff_slot_id"],
                slot_type=SlotType.dropoff,
            )
            pickup = await get_slot_for_event(
                db,
                event_id=event.id,
                slot_id=data["pickup_slot_id"],
                slot_type=SlotType.pickup,
            )
            text = build_review_text(
                event=event,
                first_name=data["participant_first_name"],
                last_name=data["participant_last_name"],
                brand=data["bicycle_brand"],
                color=data["bicycle_color"],
                dropoff=dropoff,
                pickup=pickup,
                prestart_service=prestart,
            )
    except BookingError as exc:
        await _clear_state(state)
        await callback.answer()
        await callback.message.edit_text(str(exc))
        return
    except Exception:
        logger.exception("Failed to build review")
        await _clear_state(state)
        await callback.answer()
        await callback.message.edit_text("Не удалось сформировать заявку. Начните заново.")
        return

    await callback.answer()
    await state.set_state(BookingForm.confirming)
    await callback.message.edit_text(text, reply_markup=confirm_kb())


@router.callback_query(BookingForm.confirming, F.data == "bk:confirm")
async def cb_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if data.get("submitting"):
        await callback.answer("Заявка уже обрабатывается…")
        return

    await state.update_data(submitting=True)
    await callback.answer()

    draft = BookingDraft(
        user_tg_id=callback.from_user.id,
        event_id=data["event_id"],
        participant_first_name=data["participant_first_name"],
        participant_last_name=data["participant_last_name"],
        bicycle_brand=data["bicycle_brand"],
        bicycle_color=data["bicycle_color"],
        dropoff_slot_id=data["dropoff_slot_id"],
        pickup_slot_id=data["pickup_slot_id"],
        prestart_service=bool(data["prestart_service"]),
    )

    try:
        async for db in get_session():
            booking = await create_booking(db, draft)
    except BookingError as exc:
        await _clear_state(state)
        await callback.message.edit_text(f"Не удалось оформить заявку:\n{exc}")
        return
    except Exception:
        logger.exception("Failed to create booking")
        await _clear_state(state)
        await callback.message.edit_text(
            "Произошла ошибка при сохранении заявки. Попробуйте позже."
        )
        return

    await _clear_state(state)
    status_label = booking.status.value
    await callback.message.edit_text(
        f"Заявка №{booking.id} оформлена.\n"
        f"Статус: <b>{status_label}</b>\n"
        f"Стоимость: {booking.price} ₽"
    )


@router.message(BookingForm.choosing_event)
@router.message(BookingForm.dropoff_slot)
@router.message(BookingForm.pickup_slot)
@router.message(BookingForm.prestart_service)
@router.message(BookingForm.confirming)
async def unexpected_text(message: Message) -> None:
    await message.answer(
        "Используйте кнопки ниже или нажмите «Отмена».",
        reply_markup=cancel_only_kb(),
    )


@router.message(BookingForm.first_name)
@router.message(BookingForm.last_name)
@router.message(BookingForm.bicycle_brand)
@router.message(BookingForm.bicycle_color)
async def unexpected_non_text(message: Message) -> None:
    await message.answer("Пожалуйста, отправьте текстом.")
