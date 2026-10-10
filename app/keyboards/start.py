from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


main_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="кнопка 1", callback_data="button_1")],
    [InlineKeyboardButton(text="кнопка 2", callback_data="button_2")],
    [InlineKeyboardButton(text="Поддержка", url="https://t.me/Mishanya_B/")]])
