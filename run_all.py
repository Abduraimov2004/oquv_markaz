"""Web panel + Telegram botni BITTA buyruq bilan ishga tushirish.

    python run_all.py

Eslatma: bu yerda --reload yo'q (ikkalasi bitta jarayonda). Ishlab chiqishda
web'ni --reload bilan alohida ishlatganingiz qulayroq:
    uvicorn app.main:app --reload   (alohida terminal)
    python -m bot.bot               (alohida terminal)
"""
import asyncio
import socket

import uvicorn

from app.config import settings
from app.main import app
import bot.bot as botmod  # import paytida router'lar dispatcherga ulanadi


def _lan_ip():
    """Kompyuterning WiFi/LAN IP manzilini topadi (telefondan ochish uchun)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


async def run_web():
    # host="0.0.0.0" -> bir xil WiFi'dagi telefon/boshqa qurilmalar ham ochadi
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


async def run_bot():
    if not settings.BOT_TOKEN:
        print("⚠️  BOT_TOKEN yo'q — faqat web ishlaydi.")
        return
    print("🤖 Bot ishga tushdi (long polling)...")
    await botmod.dp.start_polling(botmod.bot)


async def main():
    ip = _lan_ip()
    print("=" * 56)
    print("  Kompyuterda:  http://127.0.0.1:8000")
    print(f"  Telefonda (bir xil WiFi):  http://{ip}:8000")
    print("  (Windows 'Allow?' desa -> Ruxsat bering / Allow)")
    print("=" * 56)
    await asyncio.gather(run_web(), run_bot())


if __name__ == "__main__":
    asyncio.run(main())
