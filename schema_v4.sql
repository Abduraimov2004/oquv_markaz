-- =====================================================================
--  schema_v4 — o'qituvchi web-login + har guruhga alohida oylik to'lov
--  Supabase -> SQL Editor -> shu matn -> RUN (oldingilardan keyin).
-- =====================================================================

-- Har bir guruh (fan) o'z oylik to'loviga ega bo'lishi mumkin.
-- 0 bo'lsa — markazning standart oyligi (Sozlamalar) ishlatiladi.
alter table groups add column if not exists monthly_fee numeric not null default 0;

-- O'qituvchi endi web panelga ham kira oladi (markaz egasi parol beradi).
alter table teachers add column if not exists password_hash text;
