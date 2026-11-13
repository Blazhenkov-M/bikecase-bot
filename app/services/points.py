from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.database.models import Event, Point


@dataclass(frozen=True, slots=True)
class PointInfo:
    name: str
    address: str
    # префикс колонок дат в events: workshop | krylatskoe
    group: str


# Порядок здесь = порядок кнопок выбора точки.
POINTS: dict[Point, PointInfo] = {
    Point.zapovednaya: PointInfo("Заповедная", "Москва, ул. Заповедная", "workshop"),
    Point.starovatutinsky: PointInfo("Староватутинский", "Москва, Староватутинский пр.", "workshop"),
    Point.krylatskoe: PointInfo("Крылатское", "Москва, Крылатское", "krylatskoe"),
}


def point_dates(event: Event, point: Point, kind: str) -> tuple[date, date]:
    """Диапазон дат точки для события; kind — dropoff | pickup."""
    prefix = f"{POINTS[point].group}_{kind}"
    return getattr(event, f"{prefix}_from"), getattr(event, f"{prefix}_to")
