from __future__ import annotations

import calendar
from datetime import date

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# callback_data: cal:<kind>:m:<YYYY-MM> — листание, cal:<kind>:d:<YYYY-MM-DD> — выбор дня
CALENDAR_IGNORE = "cal:ignore"

MONTHS = (
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
)
WEEKDAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")


def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    year_shift, month_index = divmod(month - 1 + delta, 12)
    return year + year_shift, month_index + 1


def _ignore(text: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=CALENDAR_IGNORE)


def calendar_kb(
    *,
    kind: str,
    year: int,
    month: int,
    min_date: date,
    cancel_callback: str,
    extra_rows: list[list[InlineKeyboardButton]] | None = None,
) -> InlineKeyboardMarkup:
    """Месяц сеткой; дни раньше min_date неактивны. extra_rows — кнопки над «Отмена»."""
    min_month = (min_date.year, min_date.month)

    prev_year, prev_month = shift_month(year, month, -1)
    next_year, next_month = shift_month(year, month, 1)
    if (prev_year, prev_month) >= min_month:
        prev_btn = InlineKeyboardButton(
            text="«", callback_data=f"cal:{kind}:m:{prev_year}-{prev_month:02d}"
        )
    else:
        prev_btn = _ignore(" ")
    next_btn = InlineKeyboardButton(
        text="»", callback_data=f"cal:{kind}:m:{next_year}-{next_month:02d}"
    )

    rows = [
        [prev_btn, _ignore(f"{MONTHS[month - 1]} {year}"), next_btn],
        [_ignore(day) for day in WEEKDAYS],
    ]
    for week in calendar.Calendar(firstweekday=0).monthdatescalendar(year, month):
        row = []
        for day in week:
            if day.month != month:
                row.append(_ignore(" "))
            elif day < min_date:
                row.append(_ignore("·"))
            else:
                row.append(
                    InlineKeyboardButton(
                        text=str(day.day),
                        callback_data=f"cal:{kind}:d:{day.isoformat()}",
                    )
                )
        rows.append(row)

    rows.extend(extra_rows or [])
    rows.append([InlineKeyboardButton(text="Отмена", callback_data=cancel_callback)])
    return InlineKeyboardMarkup(inline_keyboard=rows)
