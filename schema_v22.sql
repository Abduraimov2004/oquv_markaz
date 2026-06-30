-- schema_v22 — FILIAL QAT'IY AJRATISH
-- Supabase SQL Editor'da RUN qiling.

-- 1) Bildirishnoma, xarajat so'rovi va xodim (admin) — filialga bog'lanadi
alter table notifications    add column if not exists branch_id uuid;
alter table expense_requests add column if not exists branch_id uuid;
alter table users            add column if not exists branch_id uuid;  -- administrator qaysi filialga tayinlangan

create index if not exists idx_notif_branch on notifications(branch_id);

-- 2) Eski (filialsiz) yozuvlarni har markazning ENG ESKI filialiga biriktiramiz
--    (faqat filiali bor markazlar uchun; filiali yo'q markazlar o'zgarmaydi)
update students s set branch_id = (
    select b.id from branches b where b.center_id = s.center_id order by b.created_at asc limit 1
) where s.branch_id is null
  and exists (select 1 from branches b where b.center_id = s.center_id);

update groups g set branch_id = (
    select b.id from branches b where b.center_id = g.center_id order by b.created_at asc limit 1
) where g.branch_id is null
  and exists (select 1 from branches b where b.center_id = g.center_id);

update teachers t set branch_id = (
    select b.id from branches b where b.center_id = t.center_id order by b.created_at asc limit 1
) where t.branch_id is null
  and exists (select 1 from branches b where b.center_id = t.center_id);

update rooms r set branch_id = (
    select b.id from branches b where b.center_id = r.center_id order by b.created_at asc limit 1
) where r.branch_id is null
  and exists (select 1 from branches b where b.center_id = r.center_id);

update leads l set branch_id = (
    select b.id from branches b where b.center_id = l.center_id order by b.created_at asc limit 1
) where l.branch_id is null
  and exists (select 1 from branches b where b.center_id = l.center_id);

update expenses e set branch_id = (
    select b.id from branches b where b.center_id = e.center_id order by b.created_at asc limit 1
) where e.branch_id is null
  and exists (select 1 from branches b where b.center_id = e.center_id);
