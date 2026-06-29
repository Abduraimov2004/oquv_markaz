-- =====================================================================
--  O'QUV MARKAZ PLATFORMASI — Supabase (PostgreSQL) baza tuzilishi
--  Multi-tenant: har bir jadvalda center_id bor. Har bir markaz faqat
--  o'z center_id'sini ko'radi. Bitta tizim, lekin har markaz alohida.
--
--  ISHLATISH: Supabase -> SQL Editor -> shu faylni to'liq joylashtiring
--  -> RUN. Hamma jadval, indeks va RLS bir martada yaratiladi.
-- =====================================================================

-- gen_random_uuid() uchun (Supabase'da odatda yoqilgan)
create extension if not exists pgcrypto;

-- ---------------------------------------------------------------------
-- 1) MARKAZLAR (tenant) — har bir o'quv markaz shu yerda bitta qator
-- ---------------------------------------------------------------------
create table if not exists centers (
    id                 uuid primary key default gen_random_uuid(),
    name               text not null,                 -- markaz nomi
    owner_name         text,                          -- direktor ismi
    phone              text,
    status             text not null default 'active',-- active | suspended
    subscription_until date,                          -- obuna tugash sanasi
    settings           jsonb not null default '{}',   -- ish vaqti, shablonlar va h.k.
    created_at         timestamptz not null default now()
);

-- ---------------------------------------------------------------------
-- 2) FOYDALANUVCHILAR (panelga kiradiganlar: superadmin + markaz egasi)
--    O'qituvchi/o'quvchi/ota-ona panelga kirmaydi — ular BOT orqali.
--    superadmin uchun center_id = NULL (u hammasini ko'radi).
-- ---------------------------------------------------------------------
create table if not exists users (
    id            uuid primary key default gen_random_uuid(),
    center_id     uuid references centers(id) on delete cascade, -- superadmin -> null
    role          text not null,                  -- superadmin | owner
    full_name     text,
    phone         text unique not null,           -- LOGIN shu telefon raqami
    email         text,
    password_hash text not null,                  -- bcrypt hash
    is_active     boolean not null default true,
    created_at    timestamptz not null default now()
);

-- ---------------------------------------------------------------------
-- 3) O'QITUVCHILAR
-- ---------------------------------------------------------------------
create table if not exists teachers (
    id          uuid primary key default gen_random_uuid(),
    center_id   uuid not null references centers(id) on delete cascade,
    full_name   text not null,
    phone       text,
    subject     text,                              -- fani
    telegram_id bigint,                            -- bot orqali bog'langach yoziladi
    created_at  timestamptz not null default now()
);

-- ---------------------------------------------------------------------
-- 4) GURUHLAR
-- ---------------------------------------------------------------------
create table if not exists groups (
    id            uuid primary key default gen_random_uuid(),
    center_id     uuid not null references centers(id) on delete cascade,
    name          text not null,                   -- masalan "Matematika A1"
    subject       text,
    teacher_id    uuid references teachers(id) on delete set null,
    schedule_days text,                            -- masalan "Du,Chor,Ju"
    schedule_time text,                            -- masalan "16:00"
    created_at    timestamptz not null default now()
);

-- ---------------------------------------------------------------------
-- 5) OTA-ONALAR (bot orqali farzandini kuzatadi)
-- ---------------------------------------------------------------------
create table if not exists parents (
    id          uuid primary key default gen_random_uuid(),
    center_id   uuid not null references centers(id) on delete cascade,
    full_name   text,
    phone       text not null,
    telegram_id bigint,
    created_at  timestamptz not null default now()
);

-- ---------------------------------------------------------------------
-- 6) O'QUVCHILAR
--    telegram_id NULL bo'lishi mumkin — bolada telefon bo'lmasligi mumkin.
--    level — xp'dan avtomatik hisoblanadi (generated column).
-- ---------------------------------------------------------------------
create table if not exists students (
    id           uuid primary key default gen_random_uuid(),
    center_id    uuid not null references centers(id) on delete cascade,
    group_id     uuid references groups(id) on delete set null,
    parent_id    uuid references parents(id) on delete set null,
    full_name    text not null,
    parent_phone text,                             -- ota-ona avtomatik bog'lanishi uchun
    telegram_id  bigint,                           -- bolada telefon bo'lmasa -> null
    xp           integer not null default 0,
    level        integer generated always as ((xp / 100) + 1) stored,
    created_at   timestamptz not null default now()
);

-- ---------------------------------------------------------------------
-- 7) TESTLAR (o'qituvchi yuklaydi — Quizizz modeli)
-- ---------------------------------------------------------------------
create table if not exists quizzes (
    id          uuid primary key default gen_random_uuid(),
    center_id   uuid not null references centers(id) on delete cascade,
    group_id    uuid references groups(id) on delete set null,
    teacher_id  uuid references teachers(id) on delete set null,
    title       text not null,
    is_active   boolean not null default true,
    created_at  timestamptz not null default now()
);

-- ---------------------------------------------------------------------
-- 8) SAVOLLAR (testga tegishli)
-- ---------------------------------------------------------------------
create table if not exists questions (
    id            uuid primary key default gen_random_uuid(),
    quiz_id       uuid not null references quizzes(id) on delete cascade,
    center_id     uuid not null references centers(id) on delete cascade,
    text          text not null,
    options       jsonb not null default '[]',     -- ["A","B","C","D"]
    correct_index integer not null default 0,       -- to'g'ri javob indeksi
    points        integer not null default 10
);

-- ---------------------------------------------------------------------
-- 9) TEST NATIJALARI
-- ---------------------------------------------------------------------
create table if not exists quiz_results (
    id           uuid primary key default gen_random_uuid(),
    center_id    uuid not null references centers(id) on delete cascade,
    student_id   uuid not null references students(id) on delete cascade,
    quiz_id      uuid not null references quizzes(id) on delete cascade,
    score        integer not null default 0,
    max_score    integer not null default 0,
    completed_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------
-- 10) DAVOMAT (bir o'quvchi bir kunda bir marta)
-- ---------------------------------------------------------------------
create table if not exists attendance (
    id         uuid primary key default gen_random_uuid(),
    center_id  uuid not null references centers(id) on delete cascade,
    group_id   uuid references groups(id) on delete set null,
    student_id uuid not null references students(id) on delete cascade,
    date       date not null default current_date,
    status     text not null default 'present',     -- present | absent | late
    created_at timestamptz not null default now(),
    unique (student_id, date)
);

-- ---------------------------------------------------------------------
-- 11) TO'LOVLAR
-- ---------------------------------------------------------------------
create table if not exists payments (
    id         uuid primary key default gen_random_uuid(),
    center_id  uuid not null references centers(id) on delete cascade,
    student_id uuid not null references students(id) on delete cascade,
    amount     numeric(12,2) not null default 0,
    due_date   date,
    paid_at    timestamptz,
    status     text not null default 'pending',     -- pending | paid | overdue
    note       text,
    created_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------
-- 12) BALL TARIXI (gamifikatsiya auditi — ixtiyoriy, lekin foydali)
-- ---------------------------------------------------------------------
create table if not exists xp_events (
    id         uuid primary key default gen_random_uuid(),
    center_id  uuid not null references centers(id) on delete cascade,
    student_id uuid not null references students(id) on delete cascade,
    points     integer not null,
    reason     text,                                -- "test", "davomat" va h.k.
    created_at timestamptz not null default now()
);

-- =====================================================================
--  INDEKSLAR — har bir tenant jadvalda center_id bo'yicha tez qidirish
-- =====================================================================
create index if not exists idx_users_center      on users(center_id);
create index if not exists idx_teachers_center    on teachers(center_id);
create index if not exists idx_groups_center      on groups(center_id);
create index if not exists idx_parents_center     on parents(center_id);
create index if not exists idx_students_center    on students(center_id);
create index if not exists idx_students_group     on students(group_id);
create index if not exists idx_quizzes_center     on quizzes(center_id);
create index if not exists idx_questions_quiz     on questions(quiz_id);
create index if not exists idx_results_center     on quiz_results(center_id);
create index if not exists idx_attendance_center  on attendance(center_id);
create index if not exists idx_attendance_date    on attendance(date);
create index if not exists idx_payments_center    on payments(center_id);
create index if not exists idx_payments_status    on payments(status);

-- telegram_id bo'yicha bot tez topishi uchun
create index if not exists idx_teachers_tg on teachers(telegram_id);
create index if not exists idx_parents_tg  on parents(telegram_id);
create index if not exists idx_students_tg on students(telegram_id);

-- =====================================================================
--  RLS (Row Level Security)
--  Hamma jadvalda RLS yoqamiz va HECH QANDAY ochiq siyosat (policy)
--  qoldirmaymiz. Bu degani: anon/public kalit bilan hech kim ma'lumotni
--  ko'rolmaydi (xavfsiz holat).
--
--  Python serveri (bu loyiha) SERVICE_ROLE kalitini ishlatadi — u RLS'ni
--  chetlab o'tadi, lekin center_id'ni HAR bir so'rovda kod darajasida
--  filtrlaydi (app/deps.py -> faqat o'z markazi). Ya'ni izolatsiya kod +
--  RLS bilan ikki qavat himoyalangan.
--
--  Keyinchalik Mini App to'g'ridan-to'g'ri Supabase'ga ulansa, shu yerga
--  aniq policy'lar qo'shamiz (auth.jwt() -> center_id).
-- =====================================================================
alter table centers       enable row level security;
alter table users         enable row level security;
alter table teachers      enable row level security;
alter table groups        enable row level security;
alter table parents       enable row level security;
alter table students      enable row level security;
alter table quizzes       enable row level security;
alter table questions     enable row level security;
alter table quiz_results  enable row level security;
alter table attendance    enable row level security;
alter table payments      enable row level security;
alter table xp_events     enable row level security;

-- Tayyor. Endi .env to'ldirib, create_admin.py ishga tushiring.
