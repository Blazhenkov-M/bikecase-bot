from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Event, EventStatus
from app.handlers.admin.filters import IsAdmin
from app.services.report import build_report, list_events_for_report, report_filename

logger = logging.getLogger(__name__)
router = Router()
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

STATUS_ICONS = {
    EventStatus.active: "🟢",
    EventStatus.registration_closed: "🔴",
    EventStatus.finished: "⚪️",
}


def _events_kb(events: list[Event]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text=f"{STATUS_ICONS[e.status]} {e.name}"[:60],
            callback_data=f"ad:rep:{e.id}",
        )]
        for e in events
    ]
    rows.append([InlineKeyboardButton(text="« Меню админа", callback_data="menu:admin")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "ad:report")
async def cb_report_list(callback: CallbackQuery, session: AsyncSession) -> None:
    events = await list_events_for_report(session)
    if not events:
        await callback.answer("Событий пока нет.", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text("Выберите событие для отчёта:", reply_markup=_events_kb(events))


@router.callback_query(F.data.regexp(r"^ad:rep:\d+$"))
async def cb_report(callback: CallbackQuery, session: AsyncSession) -> None:
    event = await session.get(Event, int(callback.data.split(":")[2]))
    if event is None:
        await callback.answer("Событие не найдено.", show_alert=True)
        return
    await callback.answer("Формирую отчёт…")
    try:
        content, count = await build_report(session, event)
    except Exception:
        logger.exception("build report failed for event %s", event.id)
        await callback.message.answer("Не удалось сформировать отчёт.")
        return
    await callback.message.answer_document(
        BufferedInputFile(content, filename=report_filename(event)),
        caption=f"{event.name}: заявок — {count}",
    )
