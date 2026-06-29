-- =====================================================================
--  schema_v10 — o'quvchi profili (kengaytirilgan) + fan bo'yicha chegirma
--  Supabase -> SQL Editor -> RUN (qayta ishlatsa ham xavfsiz).
-- =====================================================================

-- O'quvchi profili maydonlari
alter table students add column if not exists birth_date    date;
alter table students add column if not exists parent_name   text;
alter table students add column if not exists address       text;
alter table students add column if not exists note          text;
alter table students add column if not exists second_phone  text;

-- Fan (qatnashuv) bo'yicha oylik chegirma (so'mda)
alter table enrollments add column if not exists discount numeric not null default 0;
