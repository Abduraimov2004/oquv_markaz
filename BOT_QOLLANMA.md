# Bot qo'llanma — O'qituvchi & Ota-ona (MVP)

Bu hujjat MVP rejasidagi (`Oquv_Markaz_MVP_Reja`) funksiyalar botda qanday
ishlashini va nima tayyor / nima keyin ekanini ko'rsatadi.

> Avval `schema_mvp.sql`'ni Supabase'da RUN qiling (grades + lessons jadvallari).
> Keyin botni ishga tushiring: `python -m bot.bot`

---

## Qanday bog'lanadi

1. **Direktor (markaz egasi)** panelda o'qituvchi va o'quvchilarni qo'shadi
   (o'quvchiga **ota-ona telefoni** kiritiladi).
2. **O'qituvchi** botda `/start` → "👩‍🏫 O'qituvchi" → telefonini ulashadi →
   tizim uni topib bog'laydi.
3. **Ota-ona** botda `/start` → "👪 Ota-ona" → telefonini ulashadi →
   tizim shu raqamga biriktirilgan farzand(lar)ni topib bog'laydi.
   Shundan keyin xabarlar avtomatik kela boshlaydi.

> Panelda o'quvchi ro'yxatida "Ota-ona (bot)" ustuni — qaysi ota-ona ulanganini
> ko'rsatadi ("ulangan" / "kutilmoqda").

---

## O'qituvchi menyusi

**📋 Davomat** — guruhni tanlaydi → bot o'quvchilarni bittadan ko'rsatadi →
"✅ Keldi / ❌ Kelmadi" bosadi. Har bosishda **ota-onaga darrov xabar** ketadi:
*"Aziz darsga keldi (16:05)"*. (Reja 5.1)

**📝 Baho qo'yish** — guruh → o'quvchi → baho (5/4/3/2) → **tayyor izoh**
("Faol edi", "Vazifa qilmadi", "Yaxshilanyapti", "Diqqat kerak", "Izohsiz").
Ota-onaga xabar ketadi. (Reja 5.2)

**📚 Bugungi dars** — guruh → mavzu yoziladi → uy vazifa yoziladi → guruhdagi
**barcha ota-onalarga kunlik xulosa** yuboriladi. (Reja 5.3)

**👥 Mening guruhlarim** — guruhlar, o'quvchilar soni, jadval.

## Ota-ona menyusi

**👶 Farzandim** — oxirgi 10 darsdagi davomat (keldi/kelmadi) + so'nggi baholar.

**💳 To'lov holati** — to'lov holati (to'langan / kutilmoqda / muddati o'tgan).

Bundan tashqari, ota-ona **hech narsa bosmasdan** davomat, baho va kunlik
xulosa xabarlarini avtomatik oladi.

---

## MVP holati

**Tayyor ✅ (1-bosqich)**
- 2 rol (o'qituvchi, ota-ona) + super-admin
- Multi-tenant baza (center_id)
- Davomat + avtomatik ota-ona xabari
- Baho + tayyor izoh shablonlari
- Kunlik avtomatik xulosa
- Ota-ona uchun farzand holati va to'lov ko'rinishi
- Super-admin panel (markaz/guruh/o'quvchi)

**Keyin (2-bosqich) — rejaga ko'ra**
- Taraqqiyot grafigi (5.4)
- "Diqqat kerak" erta ogohlantirish (5.5)
- Guruh issiqlik xaritasi (5.6)
- O'qituvchi ↔ ota-ona yozishuvi (5.7)
- To'lov eslatmalari (5.8)
- O'qituvchi uchun Mini App (qulay ekran, grafiklar)

**Keyinroq (3-bosqich)**
- AI yordamchi (ixtiyoriy)
- Boshqa markazlarni self-service ulash

> Eslatma: rejaga ko'ra **o'yin (gamification) MVP'da yo'q**. Bazada `students`
> jadvalida `xp`/`level` ustunlari qolgan (kelajak uchun), lekin hech qayerda
> ishlatilmaydi va ko'rsatilmaydi.
