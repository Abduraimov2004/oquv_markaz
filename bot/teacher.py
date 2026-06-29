"""O'QITUVCHI bot oqimlari:
  📋 Davomat        — guruh -> har o'quvchini keldi/kelmadi -> ota-onaga avtomatik xabar
  📝 Baho qo'yish   — guruh -> o'quvchi -> baho -> tayyor izoh -> ota-onaga xabar
  📚 Bugungi dars   — guruh -> mavzu + uy vazifa -> barcha ota-onalarga kunlik xulosa
  👥 Mening guruhlarim
"""
from datetime import date, datetime

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from app.db import supabase
from app.data import enrolled_students
from bot.common import (
    T_ATT, T_GRADE, T_LESSON, T_GROUPS,
    get_teacher_by_tg, notify_parent, teacher_menu,
)

router = Router()

# Tayyor izoh shablonlari (reja 5.2)
COMMENTS = ["Faol edi", "Vazifa qilmadi", "Yaxshilanyapti", "Diqqat kerak", "Izohsiz"]


def _groups_kb(teacher_id: str, prefix: str):
    """O'qituvchi guruhlaridan inline tugmalar yasaydi."""
    groups = supabase.table("groups").select("id, name").eq("teacher_id", teacher_id).execute().data or []
    if not groups:
        return None
    rows = [[InlineKeyboardButton(text=g["name"], callback_data=f"{prefix}:{g['id']}")] for g in groups]
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ====================================================================
#  DAVOMAT (5.1) — bittadan o'quvchi, har bosishda ota-onaga xabar
# ====================================================================
@router.message(F.text == T_ATT)
async def att_start(message: Message):
    t = get_teacher_by_tg(message.from_user.id)
    if not t:
        await message.answer("Avval /start bosing.")
        return
    kb = _groups_kb(t["id"], "attg")
    if not kb:
        await message.answer("Sizga biriktirilgan guruh yo'q.")
        return
    await message.answer("Davomat — guruhni tanlang:", reply_markup=kb)


@router.callback_query(F.data.startswith("attg:"))
async def att_group(c: CallbackQuery):
    gid = c.data.split(":", 1)[1]
    await _att_show(c, gid, 0)
    await c.answer()


async def _att_show(c: CallbackQuery, gid: str, idx: int):
    students = enrolled_students(gid)
    if not students:
        await c.message.edit_text("Bu guruhda o'quvchi yo'q.")
        return
    if idx >= len(students):
        await c.message.edit_text("✅ Davomat yakunlandi. Rahmat!")
        return
    s = students[idx]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Keldi", callback_data=f"attm:{gid}:{idx}:present"),
            InlineKeyboardButton(text="❌ Kelmadi", callback_data=f"attm:{gid}:{idx}:absent"),
        ],
    ])
    await c.message.edit_text(f"Davomat ({idx + 1}/{len(students)})\n\n👤 {s['full_name']}", reply_markup=kb)


@router.callback_query(F.data.startswith("attm:"))
async def att_mark(c: CallbackQuery):
    _, gid, idx, status = c.data.split(":")
    idx = int(idx)
    students = enrolled_students(gid)

    if idx < len(students) and status in ("present", "absent"):
        s = students[idx]
        t = get_teacher_by_tg(c.from_user.id)
        cid = t["center_id"] if t else None
        today = date.today().isoformat()

        # bir o'quvchi bir kunda bir marta -> bor bo'lsa yangilaymiz
        ex = supabase.table("attendance").select("id").eq("student_id", s["id"]).eq("date", today).limit(1).execute().data
        if ex:
            supabase.table("attendance").update({"status": status, "group_id": gid}).eq("id", ex[0]["id"]).execute()
        else:
            supabase.table("attendance").insert({
                "center_id": cid, "group_id": gid, "student_id": s["id"],
                "date": today, "status": status,
            }).execute()

        # ota-onaga avtomatik xabar
        tm = datetime.now().strftime("%H:%M")
        if status == "present":
            await notify_parent(s["id"], f"✅ {s['full_name']} darsga keldi ({tm}).")
        else:
            await notify_parent(s["id"], f"❌ {s['full_name']} bugun darsga kelmadi ({tm}).")

    await _att_show(c, gid, idx + 1)
    await c.answer("Belgilandi")


# ====================================================================
#  BAHO (5.2) — guruh -> o'quvchi -> baho -> izoh shablon
# ====================================================================
@router.message(F.text == T_GRADE)
async def grade_start(message: Message):
    t = get_teacher_by_tg(message.from_user.id)
    if not t:
        await message.answer("Avval /start bosing.")
        return
    kb = _groups_kb(t["id"], "grg")
    if not kb:
        await message.answer("Sizga biriktirilgan guruh yo'q.")
        return
    await message.answer("Baho — guruhni tanlang:", reply_markup=kb)


@router.callback_query(F.data.startswith("grg:"))
async def grade_group(c: CallbackQuery):
    gid = c.data.split(":", 1)[1]
    students = enrolled_students(gid)
    if not students:
        await c.message.edit_text("Bu guruhda o'quvchi yo'q.")
        await c.answer()
        return
    rows = [[InlineKeyboardButton(text=s["full_name"], callback_data=f"grs:{s['id']}")] for s in students]
    await c.message.edit_text("O'quvchini tanlang:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await c.answer()


@router.callback_query(F.data.startswith("grs:"))
async def grade_student(c: CallbackQuery):
    sid = c.data.split(":", 1)[1]
    row = [InlineKeyboardButton(text=str(v), callback_data=f"grv:{sid}:{v}") for v in (5, 4, 3, 2)]
    await c.message.edit_text("Bahoni tanlang:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[row]))
    await c.answer()


@router.callback_query(F.data.startswith("grv:"))
async def grade_value(c: CallbackQuery):
    _, sid, val = c.data.split(":")
    rows = [[InlineKeyboardButton(text=cm, callback_data=f"grc:{sid}:{val}:{i}")] for i, cm in enumerate(COMMENTS)]
    await c.message.edit_text(f"Baho: {val}. Endi izohni tanlang:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await c.answer()


@router.callback_query(F.data.startswith("grc:"))
async def grade_comment(c: CallbackQuery):
    _, sid, val, ci = c.data.split(":")
    comment = COMMENTS[int(ci)]
    t = get_teacher_by_tg(c.from_user.id)
    srow = supabase.table("students").select("full_name, group_id").eq("id", sid).limit(1).execute().data
    sname = srow[0]["full_name"] if srow else ""
    gid = srow[0]["group_id"] if srow else None

    supabase.table("grades").insert({
        "center_id": t["center_id"] if t else None,
        "student_id": sid, "group_id": gid,
        "teacher_id": t["id"] if t else None,
        "grade": int(val),
        "comment": None if comment == "Izohsiz" else comment,
        "date": date.today().isoformat(),
    }).execute()

    txt = f"📝 {sname} uchun baho: {val}."
    if comment != "Izohsiz":
        txt += f"\nIzoh: {comment}"
    await notify_parent(sid, txt)

    done = f"✅ Baho qo'yildi: {sname} — {val}"
    if comment != "Izohsiz":
        done += f" ({comment})"
    await c.message.edit_text(done)
    await c.answer("Saqlandi")


# ====================================================================
#  BUGUNGI DARS / KUNLIK XULOSA (5.3)
# ====================================================================
class Lesson(StatesGroup):
    topic = State()
    homework = State()


@router.message(F.text == T_LESSON)
async def lesson_start(message: Message):
    t = get_teacher_by_tg(message.from_user.id)
    if not t:
        await message.answer("Avval /start bosing.")
        return
    kb = _groups_kb(t["id"], "lsg")
    if not kb:
        await message.answer("Sizga biriktirilgan guruh yo'q.")
        return
    await message.answer("Bugungi dars — guruhni tanlang:", reply_markup=kb)


@router.callback_query(F.data.startswith("lsg:"))
async def lesson_group(c: CallbackQuery, state: FSMContext):
    gid = c.data.split(":", 1)[1]
    await state.update_data(group_id=gid)
    await state.set_state(Lesson.topic)
    await c.message.edit_text("Bugun qaysi mavzu o'tildi? (matn yuboring)")
    await c.answer()


@router.message(Lesson.topic)
async def lesson_topic(message: Message, state: FSMContext):
    await state.update_data(topic=message.text)
    await state.set_state(Lesson.homework)
    await message.answer("Uyga vazifa nima? (bo'lmasa «-» yuboring)")


@router.message(Lesson.homework)
async def lesson_homework(message: Message, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    gid = data.get("group_id")
    topic = data.get("topic", "")
    hw = message.text or "-"

    t = get_teacher_by_tg(message.from_user.id)
    supabase.table("lessons").insert({
        "center_id": t["center_id"] if t else None,
        "group_id": gid, "teacher_id": t["id"] if t else None,
        "topic": topic,
        "homework": None if hw.strip() == "-" else hw,
        "date": date.today().isoformat(),
    }).execute()

    # Barcha ota-onalarga kunlik xulosa
    students = enrolled_students(gid)
    msg = f"📚 Bugungi dars\nMavzu: {topic}"
    if hw.strip() != "-":
        msg += f"\n📝 Uyga vazifa: {hw}"
    for s in students:
        await notify_parent(s["id"], msg)

    await message.answer(
        f"✅ Kunlik xulosa saqlandi va {len(students)} ta o'quvchi ota-onasiga yuborildi.",
        reply_markup=teacher_menu(),
    )


# ====================================================================
#  MENING GURUHLARIM
# ====================================================================
@router.message(F.text == T_GROUPS)
async def my_groups(message: Message):
    t = get_teacher_by_tg(message.from_user.id)
    if not t:
        await message.answer("Avval /start bosing.")
        return
    groups = supabase.table("groups").select(
        "id, name, subject, schedule_days, schedule_time"
    ).eq("teacher_id", t["id"]).execute().data or []
    if not groups:
        await message.answer("Sizga biriktirilgan guruh yo'q.")
        return
    lines = ["👥 Mening guruhlarim:\n"]
    for g in groups:
        cnt = len(enrolled_students(g["id"]))
        sched = f"{g.get('schedule_days') or ''} {g.get('schedule_time') or ''}".strip()
        sched_txt = sched if sched else "jadval yo'q"
        lines.append(f"• {g['name']} ({g.get('subject') or '—'}) — {cnt} o'quvchi\n  🕒 {sched_txt}")
    await message.answer("\n".join(lines))
