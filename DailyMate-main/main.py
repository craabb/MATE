import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from database import session_factory, init_db
from bot.middleware import DBSessionMiddleware
from bot.handlers import router
from services import run_reminder_scheduler
from core.config import settings


async def main():
    logging.basicConfig(level=logging.INFO)

    # Раскомментируйте только при первом запуске или после новой миграции
    await init_db()

    bot = Bot(token=settings.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.update.middleware(DBSessionMiddleware(session_pool=session_factory))
    dp.include_router(router)

    print("DailyMate MVP запущен")
    print(f" PostgreSQL: {settings.database_url}")

    # Запуск планировщика напоминаний
    asyncio.create_task(run_reminder_scheduler(bot))

    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nБот остановлен")