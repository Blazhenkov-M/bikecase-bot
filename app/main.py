import asyncio
import logging
import sys
from aiogram import Dispatcher

from app.handlers import start
from app.core.bot_instance import bot


async def main() -> None:
    dp = Dispatcher()
    dp.include_router(start.router)

    await bot.delete_webhook(drop_pending_updates=True)  # пропускаем входящие при старте
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        stream=sys.stdout,
                        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s")
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot stopped")
    except Exception as e:
        logging.error(f"Error while starting bot: {e}", exc_info=True)
        # exc_info=True добавит traceback в лог
