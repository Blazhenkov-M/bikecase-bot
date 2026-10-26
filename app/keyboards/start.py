from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


main_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Оформить заявку", callback_data="bk:start")],
    [InlineKeyboardButton(text="Поддержка", url="https://t.me/Mishanya_B/")],
])
