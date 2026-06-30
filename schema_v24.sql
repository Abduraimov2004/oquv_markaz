-- schema_v24 — Filial obunasi (billing) + narx sozlamalari
-- Supabase SQL Editor'da RUN qiling.

-- 1) Har filial alohida obuna
alter table branches add column if not exists sub_until    date;
alter table branches add column if not exists suspended    boolean default false;  -- superadmin OFF (bloklangan)
alter table branches add column if not exists force_active boolean default false;  -- superadmin ON (obuna tugasa ham ishlaydi)

-- 2) Markaz narx sozlamalari (superadmin belgilaydi)
alter table centers add column if not exists bill_base        numeric default 150000;  -- bitta filialning bazaviy narxi
alter table centers add column if not exists bill_per_student numeric default 0;       -- 1 o'quvchiga qo'shimcha
alter table centers add column if not exists bill_per_teacher numeric default 0;       -- 1 o'qituvchiga qo'shimcha

-- 3) Mavjud filiallarga obunani 1 yil oldinga qo'yamiz (hozir bloklanmasin)
update branches set sub_until = (current_date + interval '365 day')::date
where sub_until is null;
