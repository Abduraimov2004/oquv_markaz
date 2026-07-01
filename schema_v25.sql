-- schema_v25 — O'qituvchini arxivlash (active ustuni)
-- Supabase SQL Editor'da RUN qiling.

-- O'qituvchi "ketdi" (arxiv) holati. NULL/true = faol, false = arxivlangan.
alter table teachers add column if not exists active boolean default true;

-- Mavjud o'qituvchilarni faol qilamiz (NULL bo'lib qolmasin)
update teachers set active = true where active is null;
