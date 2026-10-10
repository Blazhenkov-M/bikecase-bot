from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from app.database.database import get_session
from app.services.user import add_or_update_user
from app.keyboards.start import main_kb

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, session=get_session):
    """
    При вызове /start сохраняем пользователя в БД и
    отвечаем приветственным сообщением.
    """
    try:
        async for db in session():  # dependency‑like вызов
            await add_or_update_user(
                tg_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                last_name=message.from_user.last_name,
                language_code=message.from_user.language_code,
                is_premium=message.from_user.is_premium,
                session=db,
            )

        await message.answer(
            f"Привет, {message.from_user.full_name} 👋",
            reply_markup=main_kb,
        )

    except Exception as e:
        print("нихуя")
        await message.answer(
            f"{e}, похоже сдохла база данных")
