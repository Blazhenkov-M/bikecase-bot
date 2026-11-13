from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.database.models import Event, EventStatus


def events_menu_kb(event: Event | None) -> InlineKeyboardMarkup:
    rows = []
    if event is None:
        rows.append([InlineKeyboardButton(text="Создать событие", callback_data="ad:ev:create")])
    else:
        # id в callback_data — чтобы старая кнопка не сработала на другом событии
        rows.append([InlineKeyboardButton(text="Редактировать событие", callback_data=f"ad:ed:{event.id}")])
        if event.status == EventStatus.active:
            rows.append([InlineKeyboardButton(text="Закрыть регистрацию", callback_data=f"ad:ev:close:{event.id}")])
        else:
            rows.append([InlineKeyboardButton(text="Открыть регистрацию", callback_data=f"ad:ev:open:{event.id}")])
        rows.append([InlineKeyboardButton(text="Завершить событие", callback_data=f"ad:ev:finish:{event.id}")])
    rows.append([InlineKeyboardButton(text="« Меню админа", callback_data="menu:admin")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def finish_confirm_kb(event_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Да, завершить", callback_data=f"ad:ev:finish_ok:{event_id}")],
        [InlineKeyboardButton(text="« Назад", callback_data="ad:events")],
    ])


def edit_menu_kb(event_id: int, range_titles: list[str], limit_titles: dict[str, str]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="Название", callback_data=f"ad:ed:{event_id}:name")],
        [InlineKeyboardButton(text="Цена", callback_data=f"ad:ed:{event_id}:price")],
    ]
    rows += [
        [InlineKeyboardButton(text=title, callback_data=f"ad:ed:{event_id}:r{idx}")]
        for idx, title in enumerate(range_titles)
    ]
    rows += [
        [InlineKeyboardButton(text=title, callback_data=f"ad:ed:{event_id}:l{kind}")]
        for kind, title in limit_titles.items()
    ]
    rows.append([InlineKeyboardButton(text="« Назад", callback_data="ad:events")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def cancel_kb(callback_data: str = "ad:events") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отмена", callback_data=callback_data)],
    ])


def back_row() -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text="« Назад", callback_data="ad:ev:back")]


def back_cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        back_row(),
        [InlineKeyboardButton(text="Отмена", callback_data="ad:events")],
    ])


def confirm_create_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Создать", callback_data="ad:ev:save")],
        back_row(),
        [InlineKeyboardButton(text="Отмена", callback_data="ad:events")],
    ])
