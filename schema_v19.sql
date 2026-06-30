-- schema_v19 — 1-daraja: coin tizimi, bildirishnomalar, to'lov turi, xarajat so'rovi
-- Supabase SQL Editor'da RUN qiling.

-- 💳 To'lov turi (naqd/karta/Click/Payme/o'tkazma)
alter table payments add column if not exists method text;
alter table expenses add column if not exists method text;

-- 🪙 Coin tranzaksiyalari (har o'quvchi bo'yicha; + topildi, - sarflandi)
create table if not exists coin_tx (
    id         uuid primary key default gen_random_uuid(),
    center_id  uuid not null references centers(id)  on delete cascade,
    student_id uuid not null references students(id) on delete cascade,
    amount     int  not null,
    reason     text,                 -- attendance | homework | test | payment | redeem | manual
    note       text,
    created_at timestamptz not null default now()
);
create index if not exists idx_coin_tx_student on coin_tx(student_id);
create index if not exists idx_coin_tx_center  on coin_tx(center_id);
-- (Coin qoidalari centers.settings -> "coins" JSON ichida saqlanadi, alohida jadval shart emas.)

-- 🔔 Bildirishnomalar (markaz ichida)
create table if not exists notifications (
    id         uuid primary key default gen_random_uuid(),
    center_id  uuid not null references centers(id) on delete cascade,
    title      text not null,
    body       text,
    kind       text default 'info',  -- info | success | warning | payment | expense
    read_at    timestamptz,
    created_at timestamptz not null default now()
);
create index if not exists idx_notif_center on notifications(center_id);

-- 🧾 Xarajat so'rovi (administrator so'raydi -> egasi tasdiqlaydi/rad etadi)
create table if not exists expense_requests (
    id            uuid primary key default gen_random_uuid(),
    center_id     uuid not null references centers(id) on delete cascade,
    requested_by  uuid,
    requested_name text,
    amount        numeric not null,
    reason        text,
    status        text not null default 'pending',  -- pending | approved | rejected
    account_id    uuid,
    decided_at    timestamptz,
    created_at    timestamptz not null default now()
);
create index if not exists idx_exp_req_center on expense_requests(center_id);
