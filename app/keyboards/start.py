from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from app.settings.config import settings


def client_menu_kb(*, is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="Оформить заявку", callback_data="bk:start")],
        [InlineKeyboardButton(text="Мои заявки", callback_data="my:list")],
        [InlineKeyboardButton(text="Поддержка", url=settings.support_url)],
    ]
    if is_admin:
        rows.append([InlineKeyboardButton(text="« Меню админа", callback_data="menu:admin")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="События", callback_data="ad:events")],
        [InlineKeyboardButton(text="Заявки", callback_data="ad:stats")],
        [InlineKeyboardButton(text="Скачать xlsx-отчёт", callback_data="ad:report")],
        [InlineKeyboardButton(text="Меню клиента", callback_data="menu:client")],
    ])
