-- =====================================================================
--  schema_v15 — admin e'loni uchun amal qilish muddati (sana)
--  Supabase -> SQL Editor -> RUN (qayta ishlatsa ham xavfsiz).
-- =====================================================================

alter table news add column if not exists expires_at date;
