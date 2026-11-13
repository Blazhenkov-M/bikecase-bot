from aiogram.filters import BaseFilter
from aiogram.types import TelegramObject

from app.settings.config import settings


def is_admin(user_id: int) -> bool:
    return user_id in settings.admin_ids


class IsAdmin(BaseFilter):
    async def __call__(self, event: TelegramObject) -> bool:
        user = getattr(event, "from_user", None)
        return bool(user and is_admin(user.id))
