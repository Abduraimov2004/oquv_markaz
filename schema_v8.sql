-- =====================================================================
--  schema_v8 — tizim egasi uchun: markaz obuna narxi + obuna to'lovlari
--  Supabase -> SQL Editor -> RUN (qayta ishlatsa ham xavfsiz).
-- =====================================================================

-- Markazning oylik obuna narxi (markaz sizga oyiga qancha to'laydi)
alter table centers add column if not exists monthly_fee numeric not null default 0;

-- OBUNA TO'LOVLARI (markazlardan tushgan pul)
create table if not exists center_payments (
    id          uuid primary key default gen_random_uuid(),
    center_id   uuid not null references centers(id) on delete cascade,
    amount      numeric not null default 0,
    months      int not null default 1,
    until       date,
    note        text,
    paid_at     timestamptz not null default now()
);
create index if not exists idx_cpay_center on center_payments(center_id);
alter table center_payments enable row level security;
