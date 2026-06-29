"""Bot yadrosi — Bot va Dispatcher bitta joyda (aylanma importni oldini oladi)."""
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from app.config import settings

bot = Bot(token=settings.BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
