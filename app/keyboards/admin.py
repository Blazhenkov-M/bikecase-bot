from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.database.models import Event
from app.services.admin import TARGETS, Target
from app.services.points import POINTS

# callback_data админки:
#   ad:ev:<id>            карточка события        ad:reg:<id>          открыть/закрыть регистрацию
#   ad:en:<id>, ad:ep:<id> название / цена         ad:w:<id>:<target>   экран окна расписания
#   ad:wd / ad:wt / ad:wx:<id>:<target>           дата / время / вкл-выкл пункта


def admin_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Создать событие", callback_data="ad:custom")],
            [InlineKeyboardButton(text="Список событий", callback_data="ad:list")],
            [InlineKeyboardButton(text="Закрыть", callback_data="ad:close")],
        ]
    )


def admin_cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data="ad:cancel")],
        ]
    )


def point_step_rows(*, same_label: str | None, can_skip: bool) -> list[list[InlineKeyboardButton]]:
    """Доп. кнопки к календарю на шаге пункта в Москве."""
    rows = []
    if same_label:
        rows.append([InlineKeyboardButton(text=f"Как у предыдущего: {same_label}", callback_data="ad:same")])
    if can_skip:
        rows.append([InlineKeyboardButton(text="Пункт не работает — пропустить", callback_data="ad:skip")])
    return rows


def admin_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Создать", callback_data="ad:create"),
                InlineKeyboardButton(text="Отмена", callback_data="ad:cancel"),
            ],
        ]
    )


def events_list_kb(events: list[Event]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{'🟢' if event.registration_open else '⛔'} #{event.id} {event.name}",
                callback_data=f"ad:ev:{event.id}",
            )
        ]
        for event in events
    ]
    rows.append([InlineKeyboardButton(text="« Меню", callback_data="ad:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _target_button_text(target: Target) -> str:
    if target.kind == "dropoff":
        return f"Приём · {POINTS[target.point].name}"
    if target.kind == "pickup":
        return f"Возврат · {POINTS[target.point].name}"
    return "Выдача на мероприятии" if target.kind == "issue" else "Сдача на мероприятии"


def event_card_kb(event: Event) -> InlineKeyboardMarkup:
    toggle = "Закрыть регистрацию ⛔" if event.registration_open else "Открыть регистрацию 🟢"
    rows = [
        [InlineKeyboardButton(text=toggle, callback_data=f"ad:reg:{event.id}")],
        [
            InlineKeyboardButton(text="Название", callback_data=f"ad:en:{event.id}"),
            InlineKeyboardButton(text="Цена", callback_data=f"ad:ep:{event.id}"),
        ],
        *(
            [
                InlineKeyboardButton(
                    text=_target_button_text(target),
                    callback_data=f"ad:w:{event.id}:{target}",
                )
            ]
            for target in TARGETS
        ),
        [InlineKeyboardButton(text="« К списку", callback_data="ad:list")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def window_kb(event_id: int, target: Target, *, exists: bool, is_active: bool) -> InlineKeyboardMarkup:
    suffix = f"{event_id}:{target}"
    if exists:
        rows = [
            [
                InlineKeyboardButton(text="Дата", callback_data=f"ad:wd:{suffix}"),
                InlineKeyboardButton(text="Время", callback_data=f"ad:wt:{suffix}"),
            ]
        ]
        if target.point is not None:
            toggle = "Выключить пункт" if is_active else "Включить пункт"
            rows.append([InlineKeyboardButton(text=toggle, callback_data=f"ad:wx:{suffix}")])
    else:
        rows = [[InlineKeyboardButton(text="Добавить пункт — выбрать дату", callback_data=f"ad:wd:{suffix}")]]
    rows.append([InlineKeyboardButton(text="« К событию", callback_data=f"ad:ev:{event_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_to_event_kb(event_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="« К событию", callback_data=f"ad:ev:{event_id}")],
        ]
    )
