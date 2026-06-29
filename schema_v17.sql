-- schema_v17 — obuna majburlash + markaz logosi
-- Supabase SQL Editor'da RUN qiling.

-- Admin "obuna tugasa ham ishlasin" deb majburiy faol qilib qo'yishi uchun:
alter table centers add column if not exists force_active boolean not null default false;

-- Markaz logosi (sidebar va loginда ko'rinadi):
alter table centers add column if not exists logo_url text;
