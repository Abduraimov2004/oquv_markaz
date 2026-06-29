"""Sozlamalar — .env faylidan o'qiladi."""
import os
from dotenv import load_dotenv

load_dotenv()  # .env faylini yuklaydi


class Settings:
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_SERVICE_KEY: str = os.getenv("SUPABASE_SERVICE_KEY", "")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-secret-change-me")
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")


settings = Settings()

if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_KEY:
    print("⚠️  Diqqat: SUPABASE_URL yoki SUPABASE_SERVICE_KEY .env'da yo'q!")
