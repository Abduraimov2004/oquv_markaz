-- =====================================================================
--  schema_v9 — o'qituvchi o'zgartirishlarini kuzatish (owner uchun audit)
--  Supabase -> SQL Editor -> RUN (qayta ishlatsa ham xavfsiz).
-- =====================================================================

create table if not exists record_edits (
    id          uuid primary key default gen_random_uuid(),
    center_id   uuid not null references centers(id) on delete cascade,
    teacher_id  uuid,
    kind        text,            -- 'attendance' | 'grade'
    student_id  uuid,
    group_id    uuid,
    date        text,
    old_value   text,
    new_value   text,
    created_at  timestamptz not null default now()
);
create index if not exists idx_redits_center on record_edits(center_id);
create index if not exists idx_redits_created on record_edits(created_at);
alter table record_edits enable row level security;
