-- schema_v20 — bayram kunlari (jadval hisobga oladi)
-- Supabase SQL Editor'da RUN qiling.

create table if not exists holidays (
    id         uuid primary key default gen_random_uuid(),
    center_id  uuid not null references centers(id) on delete cascade,
    date       date not null,
    name       text not null,
    created_at timestamptz not null default now(),
    unique (center_id, date)
);
create index if not exists idx_holidays_center on holidays(center_id);
