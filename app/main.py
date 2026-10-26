import asyncio
import logging
import sys

from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from app.core.bot_instance import bot
from app.handlers.user import booking, start
from app.handlers.admin.admin import admin_router
from app.handlers.admin.edit import edit_router


async def main() -> None:
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(start.router)
    dp.include_router(admin_router)
    dp.include_router(edit_router)
    dp.include_router(booking.router)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stdout,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    )
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot stopped")
    except Exception as e:
        logging.error(f"Error while starting bot: {e}", exc_info=True)
