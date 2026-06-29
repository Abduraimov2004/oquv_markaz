-- =====================================================================
--  schema_v16 — tug'ilgan kun tabrigi yuborilganini belgilash
--  Supabase -> SQL Editor -> RUN (qayta ishlatsa ham xavfsiz).
-- =====================================================================

alter table students add column if not exists birthday_greeted_year int;
