from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.database.models import Event, EventSlot
from app.services.booking import format_slot_label


def events_kb(events: list[Event]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=event.name, callback_data=f"bk:event:{event.id}")]
        for event in events
    ]
    rows.append([InlineKeyboardButton(text="Отмена", callback_data="bk:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def slots_kb(slots: list[EventSlot], *, kind: str, back_to: str) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=format_slot_label(slot),
                callback_data=f"bk:slot:{kind}:{slot.id}",
            )
        ]
        for slot in slots
    ]
    rows.append(
        [
            InlineKeyboardButton(text="Назад", callback_data=f"bk:back:{back_to}"),
            InlineKeyboardButton(text="Отмена", callback_data="bk:cancel"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def prestart_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Да", callback_data="bk:prestart:1"),
                InlineKeyboardButton(text="Нет", callback_data="bk:prestart:0"),
            ],
            [
                InlineKeyboardButton(text="Назад", callback_data="bk:back:pickup"),
                InlineKeyboardButton(text="Отмена", callback_data="bk:cancel"),
            ],
        ]
    )


def confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Подтвердить", callback_data="bk:confirm"),
                InlineKeyboardButton(text="Отменить", callback_data="bk:cancel"),
            ],
            [
                InlineKeyboardButton(text="Назад", callback_data="bk:back:prestart"),
            ],
        ]
    )


def cancel_only_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data="bk:cancel")],
        ]
    )


def text_nav_kb(*, back_to: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Назад", callback_data=f"bk:back:{back_to}"),
                InlineKeyboardButton(text="Отмена", callback_data="bk:cancel"),
            ],
        ]
    )
