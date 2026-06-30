-- schema_v23 — Kassa hisoblari filialga + bildirishnoma migratsiyasi
-- Supabase SQL Editor'da RUN qiling.

-- 1) Kassa hisoblari (accounts) — filialga bog'lanadi (har filial alohida kassa)
alter table accounts add column if not exists branch_id uuid;

-- 2) Eski (filialsiz) hisob va bildirishnomalarni eng eski filialga biriktiramiz
update accounts a set branch_id = (
    select b.id from branches b where b.center_id = a.center_id order by b.created_at asc limit 1
) where a.branch_id is null
  and exists (select 1 from branches b where b.center_id = a.center_id);

update notifications n set branch_id = (
    select b.id from branches b where b.center_id = n.center_id order by b.created_at asc limit 1
) where n.branch_id is null
  and exists (select 1 from branches b where b.center_id = n.center_id);
