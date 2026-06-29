"""Ota-onaga Telegram orqali xabar yuborish — WEB paneldan.

Bot alohida jarayon, lekin web panel ham to'g'ridan-to'g'ri Telegram API'ga
xabar yubora oladi (bir xil BOT_TOKEN bilan). Shu tufayli o'qituvchi web'da
davomat/baho qo'yganda ham ota-onaga xabar boradi.
"""
import httpx

from app.config import settings
from app.db import supabase


def _last9(s: str) -> str:
    return "".join(c for c in (s or "") if c.isdigit())[-9:]


def _parent_telegram(student_id: str):
    """O'quvchining ota-onasi telegram_id'sini topadi (yoki None)."""
    rows = supabase.table("students").select("parent_id, parent_phone").eq("id", student_id).limit(1).execute().data
    if not rows:
        return None
    s = rows[0]
    if s.get("parent_id"):
        p = supabase.table("parents").select("telegram_id").eq("id", s["parent_id"]).limit(1).execute().data
        if p and p[0].get("telegram_id"):
            return p[0]["telegram_id"]
    if s.get("parent_phone"):
        d = _last9(s["parent_phone"])
        parents = supabase.table("parents").select("telegram_id, phone").execute().data or []
        for p in parents:
            if p.get("telegram_id") and _last9(p.get("phone")) == d:
                return p["telegram_id"]
    return None


async def notify_telegram(chat_id, text: str):
    """To'g'ridan-to'g'ri berilgan telegram_id ga xabar yuboradi."""
    if not settings.BOT_TOKEN or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{settings.BOT_TOKEN}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=6) as client:
            await client.post(url, json={"chat_id": chat_id, "text": text})
        return True
    except Exception:
        return False


async def notify_parent(student_id: str, text: str):
    """Agar ota-ona botga ulangan bo'lsa — unga xabar yuboradi."""
    if not settings.BOT_TOKEN:
        return False
    tg = _parent_telegram(student_id)
    if not tg:
        return False
    url = f"https://api.telegram.org/bot{settings.BOT_TOKEN}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=6) as client:
            await client.post(url, json={"chat_id": tg, "text": text})
        return True
    except Exception:
        return False  # ota-ona botni bloklagan yoki tarmoq xatosi — jim o'tamiz
