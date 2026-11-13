from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.keyboards.calendar import CALENDAR_IGNORE

# Подключается последним: служебные кнопки без действия.
router = Router()


@router.callback_query(F.data == CALENDAR_IGNORE)
async def cb_calendar_ignore(callback: CallbackQuery) -> None:
    await callback.answer()
