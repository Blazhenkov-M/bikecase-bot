from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from app.handlers.admin.filters import IsAdmin
from app.services.events import get_current_event
from app.services.stats import format_stats

router = Router()
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


def _stats_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="ad:stats")],
        [InlineKeyboardButton(text="« Меню админа", callback_data="menu:admin")],
    ])


@router.callback_query(F.data == "ad:stats")
async def cb_stats(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """Счётчики заявок текущего события; та же кнопка обновляет экран."""
    event = await get_current_event(session)
    if event is None:
        await callback.answer("Активного события нет.", show_alert=True)
        return
    await state.clear()
    await callback.answer()
    # В тексте есть время обновления с секундами, поэтому повторное нажатие всегда меняет сообщение.
    await callback.message.edit_text(await format_stats(session, event), reply_markup=_stats_kb())
