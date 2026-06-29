"""TELEGRAM BOT — kirish nuqtasi (aiogram 3).

Rollarni ulaydi: common (start/bog'lanish) + teacher + parent.

Ishga tushirish (web serverdan ALOHIDA terminalda):
    python -m bot.bot
"""
import asyncio
import logging

from bot.core import bot, dp
from bot.common import router as common_router
from bot.teacher import router as teacher_router
from bot.parent import router as parent_router
from app.config import settings

logging.basicConfig(level=logging.INFO)

# Tartib muhim: avval common (start/contact), keyin teacher va parent
dp.include_router(common_router)
dp.include_router(teacher_router)
dp.include_router(parent_router)


async def main():
    if not settings.BOT_TOKEN:
        print("⚠️  BOT_TOKEN .env'da yo'q — bot ishga tushmaydi.")
        return
    print("🤖 Bot ishga tushdi (long polling)...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
