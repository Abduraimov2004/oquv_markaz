-- =====================================================================
--  schema_v13 — profil rasmi, ota-ona kabineti tokeni, guruh sig'imi,
--               navbat (waitlist)
--  Supabase -> SQL Editor -> RUN (qayta ishlatsa ham xavfsiz).
-- =====================================================================

-- O'quvchi profili: rasm + ota-ona kabineti uchun maxfiy token
alter table students add column if not exists photo_url    text;
alter table students add column if not exists access_token text;

-- Guruh sig'imi (nechta o'quvchi sig'adi)
alter table groups   add column if not exists capacity int;

-- NAVBAT (guruh to'lganda)
create table if not exists waitlist (
    id          uuid primary key default gen_random_uuid(),
    center_id   uuid not null references centers(id) on delete cascade,
    group_id    uuid references groups(id) on delete cascade,
    full_name   text not null,
    phone       text,
    note        text,
    created_at  timestamptz not null default now()
);
create index if not exists idx_waitlist_center on waitlist(center_id);
alter table waitlist enable row level security;
