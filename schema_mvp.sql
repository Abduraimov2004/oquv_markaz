-- =====================================================================
--  MVP qo'shimchasi — grades (baholar) va lessons (kunlik dars/xulosa)
--  schema.sql ALLAQACHON ishga tushgan bo'lsa, FAQAT shu faylni RUN qiling.
--  (Supabase -> SQL Editor -> shu matn -> RUN)
-- =====================================================================

-- BAHOLAR — o'qituvchi qo'ygan baho + tayyor izoh
create table if not exists grades (
    id          uuid primary key default gen_random_uuid(),
    center_id   uuid not null references centers(id) on delete cascade,
    student_id  uuid not null references students(id) on delete cascade,
    group_id    uuid references groups(id) on delete set null,
    teacher_id  uuid references teachers(id) on delete set null,
    grade       integer,                              -- 2..5
    comment     text,                                 -- tayyor shablon yoki erkin izoh
    date        date not null default current_date,
    created_at  timestamptz not null default now()
);

-- DARSLAR — kunlik xulosa uchun (mavzu + uy vazifa)
create table if not exists lessons (
    id          uuid primary key default gen_random_uuid(),
    center_id   uuid not null references centers(id) on delete cascade,
    group_id    uuid not null references groups(id) on delete cascade,
    teacher_id  uuid references teachers(id) on delete set null,
    topic       text,                                 -- bugun o'tilgan mavzu
    homework    text,                                 -- uyga vazifa
    date        date not null default current_date,
    created_at  timestamptz not null default now()
);

-- Indekslar
create index if not exists idx_grades_center  on grades(center_id);
create index if not exists idx_grades_student on grades(student_id);
create index if not exists idx_grades_date    on grades(date);
create index if not exists idx_lessons_center on lessons(center_id);
create index if not exists idx_lessons_group  on lessons(group_id);
create index if not exists idx_lessons_date   on lessons(date);

-- RLS (boshqa jadvallar bilan bir xil — service key ishlatadi)
alter table grades  enable row level security;
alter table lessons enable row level security;
