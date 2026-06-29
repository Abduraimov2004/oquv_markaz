# Ishlab chiqarishga (production) chiqarish — xavfsizlik cheklisti

Bu loyiha real markazlarda ishlatiladi (pul + bolalar ma'lumoti). Quyidagilarni
launch'dan **oldin** bajaring.

## 1. Migratsiyalarni RUN qiling (Supabase → SQL Editor)
Tartib bilan, har biri qayta ishlatsa ham xavfsiz:
```
schema_v5.sql ... schema_v10.sql
schema_v11.sql      (moliyaviy audit jurnali)
schema_rls.sql      (RLS himoyasi — pastga qarang)
```

## 2. `.env` ni to'g'rilang
- `SECRET_KEY` — kuchli, tasodifiy (kamida 32 belgi):
  ```
  python -c "import secrets; print(secrets.token_urlsafe(48))"
  ```
- `PRODUCTION=1` — zaif SECRET_KEY bilan ishga tushishni bloklaydi.
- `COOKIE_SECURE=1` — sayt HTTPS orqali ishlasagina (Cloudflare Tunnel = HTTPS).
- `SUPABASE_SERVICE_KEY` — faqat serverda. Hech qachon brauzerga/JS'ga qo'ymang.
- `.env` faylini hech qachon git'ga commit qilmang (`.gitignore`da bor).

## 3. RLS — anon kalit sizib chiqsa ham ma'lumot himoyada
`schema_rls.sql` barcha jadvalda RLS yoqadi va permissive policy QO'YMAYDI:
- Server **service_role** bilan ishlaydi → RLS chetlab o'tiladi → ilova ishlayveradi.
- Agar **anon/public** kalit qayergadir sizib chiqsa → u bilan hech narsa o'qib/yozib bo'lmaydi.

Markazlararo ajratish hozir kod darajasida (`.eq("center_id", ...)`) — har bir
so'rovda bor. Kelajakda foydalanuvchi-JWT'ga o'tsangiz, center_id bo'yicha
policy'lar qo'shasiz.

## 4. Avtomatik ishga tushish (server o'chsa)
`deploy/oquv-markaz.service` (systemd) — YO'L/USER'ni moslab:
```
sudo cp deploy/oquv-markaz.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now oquv-markaz
journalctl -u oquv-markaz -f
```

## 5. Zaxira (backup)
- Supabase → Database → Backups: **Point-in-time recovery / kunlik backup** yoqing.
- Qo'shimcha: owner panelда **Eksport (CSV)** — o'quvchilar va to'lovlarni
  vaqti-vaqti bilan yuklab, alohida saqlang.

## 6. Tekshiruv
- Login: noto'g'ri parolni 8 martdan ko'p kiritsangiz — vaqtincha bloklanadi.
- Har bir javobda xavfsizlik sarlavhalari bor (X-Frame-Options, nosniff, HSTS).
- `/docs`, `/openapi.json` o'chirilgan (API tuzilishi tashqariga ko'rinmaydi).

## 7. Yangilanish jarayoni
1. Yangi zipni eski papka ustidan oching (`.env` saqlanadi).
2. Yangi `schema_*.sql` bo'lsa — Supabase'da RUN qiling.
3. `sudo systemctl restart oquv-markaz`.
