"""Birinchi SUPERADMIN (tizim egasi — siz) ni yaratish skripti.

Ishlatish:
    python create_admin.py

Telefon, ism va parol so'raydi va users jadvaliga superadmin qo'shadi.
Bir martagina ishlatiladi (keyin shu login bilan panelga kirasiz).
"""
from app.db import supabase
from app.security import hash_password


def main():
    print("=== Superadmin yaratish ===")
    phone = input("Telefon (login uchun, masalan +998901234567): ").strip()
    name = input("Ismingiz: ").strip()
    password = input("Parol: ").strip()

    if not phone or not password:
        print("❌ Telefon va parol bo'sh bo'lmasligi kerak.")
        return

    # Bu telefon allaqachon bormi?
    exists = supabase.table("users").select("id").eq("phone", phone).limit(1).execute().data
    if exists:
        print(f"❌ {phone} allaqachon ro'yxatda.")
        return

    supabase.table("users").insert({
        "center_id": None,          # superadmin hech qaysi markazga bog'lanmaydi
        "role": "superadmin",
        "full_name": name or None,
        "phone": phone,
        "password_hash": hash_password(password),
    }).execute()

    print(f"✅ Superadmin yaratildi! Endi {phone} bilan panelga kiring.")


if __name__ == "__main__":
    main()
