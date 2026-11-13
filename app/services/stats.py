from __future__ import annotations

from datetime import datetime, timedelta
from html import escape

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Application, ApplicationStatus, Event, Point
from app.services.applications import day_counts, format_day
from app.services.events import MOSCOW, STATUS_TITLES
from app.services.points import POINTS, point_dates

KIND_TITLES = {"dropoff": "Сдача", "pickup": "Выдача"}


async def _point_counts(session: AsyncSession, event_id: int, kind: str) -> dict[Point, int]:
    column = getattr(Application, f"{kind}_point")
    rows = await session.execute(
        select(column, func.count())
        .where(Application.event_id == event_id, Application.status == ApplicationStatus.active)
        .group_by(column)
    )
    return {row[0]: row[1] for row in rows}


async def _kind_lines(session: AsyncSession, event: Event, kind: str) -> list[str]:
    points = await _point_counts(session, event.id, kind)
    lines = [f"<b>{KIND_TITLES[kind]}</b>"]
    lines += [f"{info.name} — {points.get(point, 0)}" for point, info in POINTS.items()]

    # Крылатское — по дням: занято/лимит.
    days = await day_counts(session, event.id, kind)
    limit = getattr(event, f"krylatskoe_{kind}_limit")
    start, end = point_dates(event, Point.krylatskoe, kind)
    # Дни вне диапазона возможны только у старых данных, но терять их в сводке нельзя.
    shown = sorted({start + timedelta(days=n) for n in range((end - start).days + 1)} | set(days))
    for day in shown:
        taken = days.get(day, 0)
        mark = " — мест нет" if limit is not None and taken >= limit else ""
        lines.append(f"   {format_day(day)}: {taken}/{limit if limit is not None else '∞'}{mark}")
    without_day = points.get(Point.krylatskoe, 0) - sum(days.values())
    if without_day:
        lines.append(f"   без дня: {without_day}")
    return lines


async def format_stats(session: AsyncSession, event: Event) -> str:
    """Сводка по заявкам события для админа."""
    statuses = dict(
        (await session.execute(
            select(Application.status, func.count())
            .where(Application.event_id == event.id)
            .group_by(Application.status)
        )).all()
    )
    lines = [
        f"<b>{escape(event.name)}</b>",
        f"Статус: {STATUS_TITLES[event.status]}",
        "",
        f"Активных заявок: <b>{statuses.get(ApplicationStatus.active, 0)}</b>",
        f"Отменённых: {statuses.get(ApplicationStatus.cancelled, 0)}",
    ]
    for kind in KIND_TITLES:
        lines += ["", *await _kind_lines(session, event, kind)]
    lines += ["", f"Обновлено: {datetime.now(MOSCOW):%d.%m %H:%M:%S}"]
    return "\n".join(lines)
