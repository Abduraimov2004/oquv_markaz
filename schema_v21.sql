-- schema_v21 — FILIALLAR (bitta markazda bir nechta filial)
-- Supabase SQL Editor'da RUN qiling.
-- branch_id NULL bo'lsa — "barcha filiallar" ko'rinishida chiqadi (eski ma'lumotlar buzilmaydi).

create table if not exists branches (
    id         uuid primary key default gen_random_uuid(),
    center_id  uuid not null references centers(id) on delete cascade,
    name       text not null,
    address    text,
    created_at timestamptz not null default now()
);
create index if not exists idx_branches_center on branches(center_id);

-- Har bir asosiy jadvalga filial bog'lanishi (ixtiyoriy — NULL = umumiy)
alter table students add column if not exists branch_id uuid;
alter table groups   add column if not exists branch_id uuid;
alter table teachers add column if not exists branch_id uuid;
alter table rooms    add column if not exists branch_id uuid;
alter table leads    add column if not exists branch_id uuid;
alter table expenses add column if not exists branch_id uuid;

create index if not exists idx_students_branch on students(branch_id);
create index if not exists idx_groups_branch   on groups(branch_id);
create index if not exists idx_teachers_branch on teachers(branch_id);
