from collections.abc import Collection
from datetime import date

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.database.models import Event, Point
from app.services.applications import format_day, format_point
from app.services.points import POINTS


def _nav_rows(*, back: bool) -> list[list[InlineKeyboardButton]]:
    rows = []
    if back:
        rows.append([InlineKeyboardButton(text="« Назад", callback_data="bk:back")])
    rows.append([InlineKeyboardButton(text="Отмена", callback_data="bk:cancel")])
    return rows


def consent_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Согласен", callback_data="bk:consent")],
        *_nav_rows(back=False),
    ])


def step_kb(*, back: bool) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=_nav_rows(back=back))


def points_kb(
    event: Event,
    kind: str,
    nav_rows: list[list[InlineKeyboardButton]] | None = None,
    *,
    hidden: Collection[Point] = (),
) -> InlineKeyboardMarkup:
    """hidden — точки, которые сейчас выбрать нельзя (нет свободных дней)."""
    rows = [
        [InlineKeyboardButton(text=format_point(event, point, kind), callback_data=f"bk:pt:{point.value}")]
        for point in POINTS
        if point not in hidden
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows + (nav_rows or _nav_rows(back=True)))


def days_kb(days: list[date], nav_rows: list[list[InlineKeyboardButton]] | None = None) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=format_day(day), callback_data=f"bk:day:{day.isoformat()}")]
        for day in days
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows + (nav_rows or _nav_rows(back=True)))


def confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отправить заявку", callback_data="bk:confirm")],
        *_nav_rows(back=True),
    ])
