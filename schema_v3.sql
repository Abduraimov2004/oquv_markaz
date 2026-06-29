-- =====================================================================
--  Qo'shimcha — news (yangiliklar/e'lonlar). Supabase -> SQL Editor -> RUN.
-- =====================================================================
create table if not exists news (
    id         uuid primary key default gen_random_uuid(),
    title      text not null,
    body       text,
    created_at timestamptz not null default now()
);
alter table news enable row level security;
