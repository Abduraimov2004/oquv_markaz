-- =====================================================================
--  schema_v5 — TO'LIQ migratsiya (qayta-qayta RUN qilsa ham xavfsiz)
--  Supabase -> SQL Editor -> RUN.  Hamma kerakli ustun/jadvalni kafolatlaydi.
-- =====================================================================

-- 1) Kerakli ustunlar (yetishmasa qo'shiladi)
alter table groups   add column if not exists monthly_fee        numeric not null default 0;
alter table teachers add column if not exists password_hash      text;
alter table teachers add column if not exists commission_percent numeric not null default 0;
alter table payments add column if not exists group_id           uuid references groups(id) on delete set null;

-- 2) QATNASHUV (enrollments): o'quvchi -> bir nechta fan (guruh)
create table if not exists enrollments (
    id          uuid primary key default gen_random_uuid(),
    center_id   uuid not null references centers(id) on delete cascade,
    student_id  uuid not null references students(id) on delete cascade,
    group_id    uuid not null references groups(id) on delete cascade,
    created_at  timestamptz not null default now(),
    unique (student_id, group_id)
);
create index if not exists idx_enroll_center  on enrollments(center_id);
create index if not exists idx_enroll_student on enrollments(student_id);
create index if not exists idx_enroll_group   on enrollments(group_id);
alter table enrollments enable row level security;

-- 3) O'QITUVCHI OYLIGI (qancha pul berildi)
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

-- 4) Mavjud students.group_id larni qatnashuvga ko'chiramiz (bir martalik, xavfsiz)
insert into enrollments (center_id, student_id, group_id)
select center_id, id, group_id
from students
where group_id is not null
on conflict (student_id, group_id) do nothing;
