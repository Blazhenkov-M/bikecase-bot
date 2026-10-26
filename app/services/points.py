from __future__ import annotations

from dataclasses import dataclass

from app.database.models import Point


@dataclass(frozen=True, slots=True)
class PointInfo:
    name: str
    address: str
    instructions: str | None = None


# Порядок здесь = порядок шагов при создании события и строк в сводках.
POINTS: dict[Point, PointInfo] = {
    Point.krylatskoe: PointInfo("Крылатское", "Москва, Крылатское"),
    Point.zapovednaya: PointInfo("Заповедная", "Москва, ул. Заповедная"),
    Point.starovatutinsky: PointInfo("Староватутинский", "Москва, Староватутинский пр."),
}
