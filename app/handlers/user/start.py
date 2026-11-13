import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.handlers.admin.filters import IsAdmin, is_admin
from app.keyboards.start import admin_menu_kb, client_menu_kb
from app.services.user import add_or_update_user

logger = logging.getLogger(__name__)
router = Router()

CLIENT_MENU_TEXT = "Здесь можно оформить заявку на трансфер велосипеда."
ADMIN_MENU_TEXT = "Меню админа."


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """При /start сохраняем пользователя в БД и показываем меню по роли."""
    await state.clear()
    try:
        await add_or_update_user(
            tg_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
            language_code=message.from_user.language_code,
            is_premium=message.from_user.is_premium,
            session=session,
        )
    except Exception:
        logger.exception("failed to save user %s", message.from_user.id)
        await message.answer("Что-то пошло не так, попробуйте позже.")
        return

    if is_admin(message.from_user.id):
        await message.answer(ADMIN_MENU_TEXT, reply_markup=admin_menu_kb())
        return
    await message.answer(
        f"Привет, {message.from_user.full_name} 👋\n{CLIENT_MENU_TEXT}",
        reply_markup=client_menu_kb(),
    )


@router.message(Command("admin"), IsAdmin())
async def cmd_admin(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(ADMIN_MENU_TEXT, reply_markup=admin_menu_kb())


@router.callback_query(F.data == "menu:client")
async def cb_client_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await callback.message.edit_text(
        CLIENT_MENU_TEXT,
        reply_markup=client_menu_kb(is_admin=is_admin(callback.from_user.id)),
    )


@router.callback_query(F.data == "menu:admin", IsAdmin())
async def cb_admin_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await callback.message.edit_text(ADMIN_MENU_TEXT, reply_markup=admin_menu_kb())
