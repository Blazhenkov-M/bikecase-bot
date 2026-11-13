import asyncio
import logging
import sys
from datetime import datetime

from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from app.core.bot_instance import bot
from app.handlers import stubs
from app.handlers.admin import edit, events, report, stats
from app.handlers.user import booking, my_applications, start
from app.middlewares.db import DbSessionMiddleware
from app.services.events import MOSCOW


async def main() -> None:
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.middleware(DbSessionMiddleware())
    dp.include_router(start.router)
    dp.include_router(events.router)
    dp.include_router(edit.router)
    dp.include_router(report.router)
    dp.include_router(stats.router)
    dp.include_router(booking.router)
    dp.include_router(my_applications.router)
    # stubs — последним
    dp.include_router(stubs.router)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    # Время в логах — всегда московское (UTC+3), независимо от таймзоны сервера/контейнера
    logging.Formatter.converter = lambda *args: datetime.fromtimestamp(args[-1], MOSCOW).timetuple()
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
