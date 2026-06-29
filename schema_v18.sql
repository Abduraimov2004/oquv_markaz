-- schema_v18 — markaz/tizim logosi, o'qituvchi rasmi, tizim sozlamalari
-- Supabase SQL Editor'da RUN qiling. (v17 ni o'tkazib yuborgan bo'lsangiz ham,
--  bu fayl uning ustunlarini ham qo'shadi — xavfsiz, takror RUN qilsa ham OK.)

-- Markaz: obuna majburlash + logo
alter table centers  add column if not exists force_active boolean not null default false;
alter table centers  add column if not exists logo_url    text;

-- O'qituvchi rasmi
alter table teachers add column if not exists photo_url   text;

-- Tizim (superadmin) sozlamalari — bitta qator (id=1), JSON ichida saqlanadi
create table if not exists system_settings (
    id   int primary key default 1,
    data jsonb not null default '{}'::jsonb
);
insert into system_settings (id, data) values (1, '{}'::jsonb)
    on conflict (id) do nothing;
