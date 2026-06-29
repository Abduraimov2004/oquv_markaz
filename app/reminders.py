"""Kunlik avtomatik eslatmalar — ota-onalarga Telegram orqali.

Ishga tushirish (kuniga bir marta):
    python -m app.reminders

Windows: Task Scheduler -> har kuni 09:00 -> shu buyruq.
Linux/WSL: crontab -> 0 9 * * *  cd /path && .venv/bin/python -m app.reminders

Yuboriladi:
  • To'lov eslatmasi — qarzi bor faol o'quvchilar ota-onasiga.
  • Tug'ilgan kun tabrigi — bugun tug'ilgan o'quvchilarga.
"""
import asyncio

from app.db import supabase
from app import data
from app.notify import notify_parent


def _fmt(n):
    return f"{int(n):,}".replace(",", " ")


async def run():
    try:
        centers = supabase.table("centers").select("id, name, status").execute().data or []
    except Exception as e:
        print("centers o'qishda xato:", e)
        return

    total_pay = 0
    for c in centers:
        if c.get("status") != "active":
            continue
        cid = c["id"]
        cname = c.get("name") or "O'quv markaz"

        # To'lov eslatmasi (qarzdorlar)
        try:
            debts = data.center_debtors(cid)
            if debts:
                students = {s["id"]: s for s in (supabase.table("students").select("id, full_name, active").eq("center_id", cid).execute().data or [])}
                for sid, d in debts.items():
                    s = students.get(sid)
                    if not s or s.get("active", True) is False or d <= 0:
                        continue
                    ok = await notify_parent(sid, f"💳 Hurmatli ota-ona! {s['full_name']} bo'yicha {_fmt(d)} so'm to'lov kutilmoqda. Iltimos, qulay vaqtda to'lab qo'ying. — {cname}")
                    if ok:
                        total_pay += 1
        except Exception as e:
            print(f"[{cname}] to'lov eslatma xato:", e)

    print(f"Yuborildi — to'lov eslatmasi: {total_pay}")


if __name__ == "__main__":
    asyncio.run(run())
