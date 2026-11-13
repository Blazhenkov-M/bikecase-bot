from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.database.models import Application
from app.services.applications import TEXT_FIELDS


def applications_list_kb(applications: list[Application]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"№{a.id} · {a.event.name}"[:60], callback_data=f"my:app:{a.id}")]
        for a in applications
    ]
    rows.append([InlineKeyboardButton(text="« Меню", callback_data="menu:client")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def application_card_kb(application_id: int, *, editable: bool) -> InlineKeyboardMarkup:
    rows = []
    if editable:
        rows.append([InlineKeyboardButton(text="Изменить", callback_data=f"my:ed:{application_id}")])
        rows.append([InlineKeyboardButton(text="Отменить заявку", callback_data=f"my:cancel:{application_id}")])
    rows.append([InlineKeyboardButton(text="« К списку заявок", callback_data="my:list")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def edit_fields_kb(application_id: int) -> InlineKeyboardMarkup:
    fields = [(field, label) for field, (label, _) in TEXT_FIELDS.items()]
    fields += [("dropoff_point", "Точка сдачи"), ("pickup_point", "Точка получения")]
    rows = [
        [InlineKeyboardButton(text=label, callback_data=f"my:ed:{application_id}:{field}")]
        for field, label in fields
    ]
    rows.append([InlineKeyboardButton(text="« Назад", callback_data=f"my:app:{application_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_to_edit_rows(application_id: int) -> list[list[InlineKeyboardButton]]:
    return [[InlineKeyboardButton(text="« Назад", callback_data=f"my:ed:{application_id}")]]


def cancel_confirm_kb(application_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Да, отменить", callback_data=f"my:cancel_ok:{application_id}")],
        [InlineKeyboardButton(text="« Назад", callback_data=f"my:app:{application_id}")],
    ])
