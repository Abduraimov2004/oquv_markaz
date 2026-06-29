"""Umumiy: /start, rol tanlash (o'qituvchi / ota-ona), telefon orqali bog'lash,
menyu klaviaturalari va ota-onaga xabar yuborish yordamchisi.

MVP: faqat 2 rol — o'qituvchi va ota-ona (rejaga ko'ra, bola tomoni yo'q).
"""
from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
)

from app.db import supabase
from bot.core import bot

router = Router()

# --- Menyu tugmalari (boshqa fayllar shu nomlar bo'yicha filtrlaydi) ---
T_ATT = "📋 Davomat"
T_GRADE = "📝 Baho qo'yish"
T_LESSON = "📚 Bugungi dars"
T_GROUPS = "👥 Mening guruhlarim"

P_CHILD = "👶 Farzandim"
P_PAY = "💳 To'lov holati"


def teacher_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=T_ATT), KeyboardButton(text=T_GRADE)],
            [KeyboardButton(text=T_LESSON), KeyboardButton(text=T_GROUPS)],
        ],
        resize_keyboard=True,
    )


def parent_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=P_CHILD), KeyboardButton(text=P_PAY)]],
        resize_keyboard=True,
    )


def last9(s: str) -> str:
    """Telefonning oxirgi 9 raqami (format farqini hisobga olmaslik uchun)."""
    return "".join(c for c in (s or "") if c.isdigit())[-9:]


def get_teacher_by_tg(tg_id: int):
    r = supabase.table("teachers").select("*").eq("telegram_id", tg_id).limit(1).execute().data
    return r[0] if r else None


def get_parent_by_tg(tg_id: int):
    r = supabase.table("parents").select("*").eq("telegram_id", tg_id).limit(1).execute().data
    return r[0] if r else None


async def notify_parent(student_id: str, text: str):
    """O'quvchining ota-onasiga (agar bog'langan bo'lsa) xabar yuboradi."""
    rows = supabase.table("students").select("parent_id, parent_phone").eq("id", student_id).limit(1).execute().data
    if not rows:
        return
    s = rows[0]
    tg = None
    if s.get("parent_id"):
        p = supabase.table("parents").select("telegram_id").eq("id", s["parent_id"]).limit(1).execute().data
        tg = p[0]["telegram_id"] if p else None
    if not tg and s.get("parent_phone"):
        d = last9(s["parent_phone"])
        parents = supabase.table("parents").select("telegram_id, phone").execute().data or []
        for p in parents:
            if p.get("telegram_id") and last9(p.get("phone")) == d:
                tg = p["telegram_id"]
                break
    if tg:
        try:
            await bot.send_message(tg, text)
        except Exception:
            pass  # ota-ona botni bloklagan bo'lishi mumkin — jim o'tamiz


# Foydalanuvchi tanlagan rol (vaqtincha, xotirada)
chosen_role: dict[int, str] = {}


@router.message(CommandStart())
async def start(message: Message):
    # Allaqachon bog'langan bo'lsa — to'g'ridan-to'g'ri menyu
    t = get_teacher_by_tg(message.from_user.id)
    if t:
        await message.answer(f"Salom, {t['full_name']}! 👩‍🏫", reply_markup=teacher_menu())
        return
    p = get_parent_by_tg(message.from_user.id)
    if p:
        await message.answer("Salom! 👪 Asosiy menyu:", reply_markup=parent_menu())
        return

    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="👩‍🏫 O'qituvchi")], [KeyboardButton(text="👪 Ota-ona")]],
        resize_keyboard=True,
    )
    await message.answer(
        "Assalomu alaykum! O'quv markaz botiga xush kelibsiz.\n\nKim sifatida kirasiz?",
        reply_markup=kb,
    )


@router.message(F.text.in_({"👩‍🏫 O'qituvchi", "👪 Ota-ona"}))
async def role_chosen(message: Message):
    chosen_role[message.from_user.id] = "teacher" if "qituvchi" in message.text else "parent"
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Telefon raqamni ulashish", request_contact=True)]],
        resize_keyboard=True,
    )
    await message.answer("Sizni tizimda topish uchun telefon raqamingizni ulashing 👇", reply_markup=kb)


@router.message(F.contact)
async def contact_shared(message: Message):
    role = chosen_role.get(message.from_user.id)
    if not role:
        await message.answer("Avval /start bosing va rolni tanlang.")
        return

    d = last9(message.contact.phone_number)
    tg = message.from_user.id

    if role == "teacher":
        rows = supabase.table("teachers").select("id, full_name, phone").execute().data or []
        found = next((r for r in rows if last9(r.get("phone")) == d), None)
        if found:
            supabase.table("teachers").update({"telegram_id": tg}).eq("id", found["id"]).execute()
            await message.answer(
                f"✅ Bog'landingiz! Xush kelibsiz, {found['full_name']}.",
                reply_markup=teacher_menu(),
            )
        else:
            await message.answer(
                "❌ Bu raqam tizimda topilmadi.\nMarkaz administratoriga murojaat qiling.",
                reply_markup=ReplyKeyboardRemove(),
            )
        return

    # role == "parent"
    students = supabase.table("students").select("id, center_id, full_name, parent_phone").execute().data or []
    matched = [s for s in students if last9(s.get("parent_phone")) == d]
    if not matched:
        await message.answer(
            "❌ Bu raqam tizimda topilmadi.\n"
            "Farzandingiz markazda ro'yxatdan o'tganini va to'g'ri raqam kiritilganini tekshiring.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    center_id = matched[0]["center_id"]
    existing = supabase.table("parents").select("id").eq("telegram_id", tg).limit(1).execute().data
    if existing:
        parent_id = existing[0]["id"]
        supabase.table("parents").update({"phone": message.contact.phone_number}).eq("id", parent_id).execute()
    else:
        ins = supabase.table("parents").insert({
            "center_id": center_id,
            "phone": message.contact.phone_number,
            "telegram_id": tg,
        }).execute().data
        parent_id = ins[0]["id"]

    # Farzand(lar)ni shu ota-onaga bog'laymiz
    for s in matched:
        supabase.table("students").update({"parent_id": parent_id}).eq("id", s["id"]).execute()

    names = ", ".join(s["full_name"] for s in matched)
    await message.answer(
        f"✅ Bog'landingiz!\nFarzand(lar): {names}\n\n"
        "Endi davomat, baho va kunlik xulosalar shu yerga avtomatik keladi.",
        reply_markup=parent_menu(),
    )
