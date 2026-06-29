"""OTA-ONA bot oqimlari:
  👶 Farzandim      — oxirgi davomat + so'nggi baholar
  💳 To'lov holati  — to'lov holati

Xabarlar (davomat, baho, kunlik xulosa) o'qituvchi amallaridan AVTOMATIK keladi.
"""
from aiogram import Router, F
from aiogram.types import Message

from app.db import supabase
from bot.common import P_CHILD, P_PAY, get_parent_by_tg

router = Router()

PAY_STATUS = {
    "paid": "to'langan ✅",
    "pending": "kutilmoqda ⏳",
    "overdue": "muddati o'tgan ❗",
}


@router.message(F.text == P_CHILD)
async def child_status(message: Message):
    p = get_parent_by_tg(message.from_user.id)
    if not p:
        await message.answer("Avval /start bosing.")
        return
    students = supabase.table("students").select("id, full_name").eq("parent_id", p["id"]).execute().data or []
    if not students:
        await message.answer("Farzand topilmadi. Markaz administratoriga murojaat qiling.")
        return

    blocks = []
    for s in students:
        att = (
            supabase.table("attendance").select("status, date")
            .eq("student_id", s["id"]).order("date", desc=True).limit(10).execute().data
        ) or []
        present = sum(1 for a in att if a["status"] in ("present", "late"))
        absent = sum(1 for a in att if a["status"] == "absent")
        grades = (
            supabase.table("grades").select("grade, comment, date")
            .eq("student_id", s["id"]).order("date", desc=True).limit(3).execute().data
        ) or []

        b = [f"👶 {s['full_name']}", f"Oxirgi 10 dars: {present} keldi, {absent} kelmadi"]
        if grades:
            b.append("So'nggi baholar:")
            for g in grades:
                line = f"  • {g['date']}: baho {g['grade']}"
                if g.get("comment"):
                    line += f" — {g['comment']}"
                b.append(line)
        else:
            b.append("Hali baho yo'q.")
        blocks.append("\n".join(b))

    await message.answer("\n\n".join(blocks))


@router.message(F.text == P_PAY)
async def payment_status(message: Message):
    p = get_parent_by_tg(message.from_user.id)
    if not p:
        await message.answer("Avval /start bosing.")
        return
    students = supabase.table("students").select("id, full_name").eq("parent_id", p["id"]).execute().data or []
    if not students:
        await message.answer("Farzand topilmadi.")
        return

    blocks = []
    for s in students:
        pays = (
            supabase.table("payments").select("amount, due_date, status")
            .eq("student_id", s["id"]).order("due_date", desc=True).limit(5).execute().data
        ) or []
        b = [f"💳 {s['full_name']}"]
        if not pays:
            b.append("  To'lov ma'lumoti yo'q.")
        for pay in pays:
            amt_txt = f"{int(pay['amount']):,}".replace(",", " ")
            st = PAY_STATUS.get(pay["status"], pay["status"])
            due = pay.get("due_date") or "—"
            b.append(f"  • {amt_txt} so'm — {st} (muddat: {due})")
        blocks.append("\n".join(b))

    await message.answer("\n\n".join(blocks))
