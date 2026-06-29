-- =====================================================================
--  schema_v7 — lid->fan bog'lash, o'quvchi "faol/ketgan", to'lov backfill
--  Supabase -> SQL Editor -> RUN (qayta ishlatsa ham xavfsiz).
-- =====================================================================

-- 1) Lidda tanlangan guruh (fan)
alter table leads add column if not exists group_id uuid references groups(id) on delete set null;

-- 2) O'quvchi holati: faol / ketgan (arxiv)
alter table students add column if not exists active boolean not null default true;

-- 3) BACKFILL: group_id'siz to'lovlarni o'quvchining yagona faniga bog'laymiz
--    (faqat 1 ta fanga yozilgan o'quvchilar uchun — chalkashlik bo'lmasin)
update payments p
set group_id = e.group_id
from enrollments e
where p.group_id is null
  and e.student_id = p.student_id
  and (select count(*) from enrollments e2 where e2.student_id = p.student_id) = 1;
