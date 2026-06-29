-- =====================================================================
--  schema_v6 — CRM (lidlar) + Dars jadvali/Xonalar + Kassa (chiqim)
--  Supabase -> SQL Editor -> RUN (qayta ishlatsa ham xavfsiz).
-- =====================================================================

-- XONALAR
create table if not exists rooms (
    id          uuid primary key default gen_random_uuid(),
    center_id   uuid not null references centers(id) on delete cascade,
    name        text not null,
    capacity    int,
    created_at  timestamptz not null default now()
);
create index if not exists idx_rooms_center on rooms(center_id);
alter table rooms enable row level security;

-- DARS JADVALI (har guruhga bir nechta vaqt bo'lagi)
create table if not exists schedule_slots (
    id          uuid primary key default gen_random_uuid(),
    center_id   uuid not null references centers(id) on delete cascade,
    group_id    uuid not null references groups(id) on delete cascade,
    room_id     uuid references rooms(id) on delete set null,
    weekday     int  not null,           -- 1=Du ... 7=Yak
    start_time  text not null,           -- "16:00"
    end_time    text not null,           -- "17:30"
    created_at  timestamptz not null default now()
);
create index if not exists idx_slot_center on schedule_slots(center_id);
create index if not exists idx_slot_group  on schedule_slots(group_id);
alter table schedule_slots enable row level security;

-- CRM — LIDLAR (potensial o'quvchilar, sinov darsi)
create table if not exists leads (
    id          uuid primary key default gen_random_uuid(),
    center_id   uuid not null references centers(id) on delete cascade,
    full_name   text not null,
    phone       text,
    subject     text,
    source      text,                    -- qayerdan keldi (Instagram, tanish...)
    status      text not null default 'new',  -- new/contacted/trial/enrolled/lost
    note        text,
    trial_date  date,
    student_id  uuid references students(id) on delete set null,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);
create index if not exists idx_leads_center on leads(center_id);
create index if not exists idx_leads_status on leads(status);
alter table leads enable row level security;

-- KASSA — CHIQIMLAR (ijara, kommunal, reklama...)
create table if not exists expenses (
    id          uuid primary key default gen_random_uuid(),
    center_id   uuid not null references centers(id) on delete cascade,
    category    text,
    amount      numeric not null default 0,
    note        text,
    spent_at    timestamptz not null default now(),
    created_at  timestamptz not null default now()
);
create index if not exists idx_expenses_center on expenses(center_id);
alter table expenses enable row level security;

-- O'QITUVCHI OYLIGI (oldingi migratsiyada bo'lmagan bo'lsa — kafolat)
create table if not exists teacher_payouts (
    id          uuid primary key default gen_random_uuid(),
    center_id   uuid not null references centers(id) on delete cascade,
    teacher_id  uuid not null references teachers(id) on delete cascade,
    amount      numeric not null default 0,
    note        text,
    paid_at     timestamptz not null default now()
);
create index if not exists idx_payout_center  on teacher_payouts(center_id);
create index if not exists idx_payout_teacher on teacher_payouts(teacher_id);
alter table teacher_payouts enable row level security;
