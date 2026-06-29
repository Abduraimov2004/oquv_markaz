-- =====================================================================
--  schema_v11 — HISOBLAR (naqd / karta / click / payme) + balans
--  Har pul harakati qaysi hisobga tushgani/chiqqani yoziladi.
--  Supabase -> SQL Editor -> RUN (qayta ishlatsa ham xavfsiz).
-- =====================================================================

-- Markazning pul hisoblari (kassalar)
create table if not exists accounts (
    id              uuid primary key default gen_random_uuid(),
    center_id       uuid not null references centers(id) on delete cascade,
    name            text not null,                 -- "Naqd", "Uzcard ...", "Click"
    kind            text not null default 'cash',  -- cash | card | click | payme | other
    card_number     text,                          -- karta raqami (ixtiyoriy)
    opening_balance numeric not null default 0,    -- boshlang'ich qoldiq
    is_active       boolean not null default true,
    sort            int not null default 0,
    created_at      timestamptz not null default now()
);
create index if not exists idx_accounts_center on accounts(center_id);
alter table accounts enable row level security;

-- Pul harakatlariga hisob + usulni bog'laymiz
alter table payments        add column if not exists account_id uuid references accounts(id) on delete set null;
alter table payments        add column if not exists method     text;     -- naqd/karta/click/payme
alter table teacher_payouts add column if not exists account_id uuid references accounts(id) on delete set null;
alter table teacher_payouts add column if not exists method     text;
alter table expenses        add column if not exists account_id uuid references accounts(id) on delete set null;
alter table expenses        add column if not exists method     text;
alter table center_payments add column if not exists account_id uuid references accounts(id) on delete set null;
alter table center_payments add column if not exists method     text;
