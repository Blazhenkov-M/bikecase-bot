from __future__ import annotations

import re
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Application, ApplicationStatus, Event
from app.services.events import format_range
from app.services.points import POINTS, point_dates

HEADERS = (
    "№", "Имя", "Фамилия", "Телефон", "Велосипед",
    "Точка сдачи", "Дата сдачи", "Точка выдачи", "Дата выдачи",
)
COLUMN_WIDTHS = (5, 18, 22, 20, 30, 20, 25, 20, 25)


def _dates(event: Event, application: Application, kind: str) -> str:
    """Выбранный день (Крылатское) либо диапазон дат точки."""
    day = getattr(application, f"{kind}_date")
    if day is not None:
        return f"{day:%d.%m.%Y}"
    return format_range(*point_dates(event, getattr(application, f"{kind}_point"), kind))


async def list_events_for_report(session: AsyncSession) -> list[Event]:
    """Все события, включая архив, новые сверху."""
    result = await session.scalars(select(Event).order_by(Event.created_at.desc()).limit(20))
    return list(result)


def report_filename(event: Event) -> str:
    name = re.sub(r"[^\w\- ]+", "", event.name).strip().replace(" ", "_") or "event"
    return f"{name[:50]}_{event.workshop_dropoff_from:%Y-%m-%d}.xlsx"


async def build_report(session: AsyncSession, event: Event) -> tuple[bytes, int]:
    """xlsx с активными заявками события → (содержимое файла, число заявок)."""
    applications = (await session.scalars(
        select(Application)
        .where(Application.event_id == event.id, Application.status == ApplicationStatus.active)
        .order_by(Application.created_at)
    )).all()

    wb = Workbook()
    ws = wb.active
    ws.title = "Заявки"
    ws.append(HEADERS)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for idx, width in enumerate(COLUMN_WIDTHS, start=1):
        ws.column_dimensions[ws.cell(row=1, column=idx).column_letter].width = width
    ws.freeze_panes = "A2"

    for number, a in enumerate(applications, start=1):
        ws.append((
            number,
            a.first_name,
            a.last_name,
            a.phone,
            f"{a.bicycle_brand}, {a.bicycle_color}",
            POINTS[a.dropoff_point].name,
            _dates(event, a, "dropoff"),
            POINTS[a.pickup_point].name,
            _dates(event, a, "pickup"),
        ))

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue(), len(applications)
