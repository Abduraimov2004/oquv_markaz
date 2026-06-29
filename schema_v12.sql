-- =====================================================================
--  schema_v12 — administrator (reception) huquqlari
--  Owner har bir administratorga qaysi panellar ko'rinishini belgilaydi.
--  Supabase -> SQL Editor -> RUN (qayta ishlatsa ham xavfsiz).
-- =====================================================================

-- Ruxsat etilgan panellar ro'yxati (vergul bilan): "students,payments,..."
alter table users add column if not exists permissions text;
