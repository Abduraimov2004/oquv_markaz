"""Sinov uchun TASODIFIY ma'lumot qo'shish skripti.

6 ta fan, har biriga: 1 o'qituvchi + 1 guruh + 5 o'quvchi.
Jami: 6 o'qituvchi, 6 guruh, 30 o'quvchi.

Ishlatish (loyiha ildizidan, .env to'ldirilgan holda):
    python seed_data.py

Eslatma: har safar ishga tushirilsa, YANGI ma'lumot qo'shadi (bir marta yetadi).
"""
import random

from app.db import supabase

# 6 ta fan
SUBJECTS = ["Matematika", "Ingliz tili", "Fizika", "Kimyo", "Biologiya", "Informatika"]

FIRST_NAMES = [
    "Aziz", "Sardor", "Jasur", "Bekzod", "Diyor", "Otabek", "Akmal", "Sherzod",
    "Farrux", "Nodir", "Javohir", "Islom", "Abror", "Doniyor", "Ulug'bek",
    "Dilnoza", "Madina", "Sevara", "Nigora", "Kamola", "Zarina", "Malika",
    "Gulnoza", "Ozoda", "Shahnoza", "Feruza", "Laylo", "Munisa", "Sabina", "Robiya",
]
LAST_NAMES = [
    "Aliyev", "Karimov", "Yusupov", "Rashidov", "Toshmatov", "Saidov", "Umarov",
    "Rahimov", "Ergashev", "Qodirov", "Ismoilov", "Nazarov", "Mirzayev",
    "Abdullayev", "Xolmatov", "Sobirov", "Yo'ldoshev", "G'aniyev", "Tursunov", "Hakimov",
]
SUFFIX = ["A1", "B1", "C1", "A2", "B2"]
DAYS = ["Du,Chor,Ju", "Se,Pay,Sha", "Du,Se,Chor", "Pay,Ju,Sha"]
TIMES = ["09:00", "10:30", "13:00", "15:00", "16:30", "18:00"]


def rnd_phone() -> str:
    code = random.choice(["90", "91", "93", "94", "95", "97", "98", "99", "88", "33"])
    tail = "".join(random.choice("0123456789") for _ in range(7))
    return "+998" + code + tail


def rnd_name() -> str:
    return f"{random.choice(LAST_NAMES)} {random.choice(FIRST_NAMES)}"


def pick_center() -> str | None:
    centers = supabase.table("centers").select("id, name").order("created_at").execute().data or []
    if not centers:
        print("❌ Markaz topilmadi. Avval super-admin panelda markaz qo'shing.")
        return None
    if len(centers) == 1:
        print(f"Markaz: {centers[0]['name']}")
        return centers[0]["id"]
    print("Markazni tanlang:")
    for i, c in enumerate(centers, 1):
        print(f"  {i}. {c['name']}")
    try:
        idx = int(input("Raqam: ").strip()) - 1
        return centers[idx]["id"]
    except (ValueError, IndexError):
        print("❌ Noto'g'ri tanlov.")
        return None


def main():
    cid = pick_center()
    if not cid:
        return

    t_count = g_count = s_count = 0
    for subj in SUBJECTS:
        # 1) o'qituvchi
        teacher = supabase.table("teachers").insert({
            "center_id": cid,
            "full_name": rnd_name(),
            "phone": rnd_phone(),
            "subject": subj,
        }).execute().data[0]
        t_count += 1

        # 2) guruh (shu o'qituvchiga biriktirilgan)
        group = supabase.table("groups").insert({
            "center_id": cid,
            "name": f"{subj} {random.choice(SUFFIX)}",
            "subject": subj,
            "teacher_id": teacher["id"],
            "schedule_days": random.choice(DAYS),
            "schedule_time": random.choice(TIMES),
        }).execute().data[0]
        g_count += 1

        # 3) 5 ta o'quvchi (bitta insert bilan)
        students = [{
            "center_id": cid,
            "group_id": group["id"],
            "full_name": rnd_name(),
            "parent_phone": rnd_phone(),
        } for _ in range(5)]
        supabase.table("students").insert(students).execute()
        s_count += len(students)

        print(f"  ✓ {subj}: {teacher['full_name']} + 5 o'quvchi")

    print(f"\n✅ Tayyor: {t_count} o'qituvchi, {g_count} guruh, {s_count} o'quvchi qo'shildi.")
    print("Panelni yangilab (F5) ko'ring.")


if __name__ == "__main__":
    main()
