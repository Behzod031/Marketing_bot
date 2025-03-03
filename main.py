import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.bot import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOTS_CONFIG
from bot_logic import setup_bot_handlers

async def run_single_bot(bot_name: str):
    """
    Функция для запуска одного бота на основе конфигурации.
    """
    bot_config = BOTS_CONFIG[bot_name]
    token = bot_config["TOKEN"]

    # Создание бота с параметром parse_mode
    bot = Bot(
        token=token,
        default=DefaultBotProperties(parse_mode="HTML")
    )
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    # Подключаем хэндлеры
    setup_bot_handlers(dp, bot_config)

    # Запуск бота (polling)
    await dp.start_polling(bot)

async def run_all_bots():
    """
    Запускает все ботов из BOTS_CONFIG одновременно.
    """
    tasks = []
    for bot_name in BOTS_CONFIG.keys():
        tasks.append(asyncio.create_task(run_single_bot(bot_name)))
    await asyncio.gather(*tasks)

def main():
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_all_bots())

if __name__ == "__main__":
    main()
