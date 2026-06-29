-- =====================================================================
--  schema_rls — RLS (Row Level Security) himoyasi
--  Supabase -> SQL Editor -> RUN (qayta ishlatsa ham xavfsiz).
--
--  MAQSAD: barcha jadvallarda RLS yoqiladi va PERMISSIVE policy
--  QO'YILMAYDI. Natijada:
--    • SERVICE_ROLE kaliti (server ishlatadi) — RLS'ni chetlab o'tadi,
--      shuning uchun ilova normal ishlayveradi.
--    • ANON / PUBLIC kalit (agar bordur-da, sizib chiqsa) — HECH QANDAY
--      ma'lumotni o'qiy/yoza olmaydi. Bu eng keng tarqalgan xatodan
--      (anon kalitni oshkor qilib qo'yish) himoya qiladi.
--
--  DIQQAT: markazlararo izolatsiya HOZIR kod darajasida (.eq center_id)
--  ta'minlanadi, chunki server service-role bilan ishlaydi. Kelajakda
--  har bir foydalanuvchi uchun alohida JWT'ga o'tsangiz — bu yerga
--  center_id bo'yicha policy'lar qo'shasiz.
-- =====================================================================

do $$
declare t text;
begin
  foreach t in array array[
    'centers','users','teachers','groups','students','parents',
    'enrollments','attendance','grades','lessons','payments',
    'teacher_payouts','expenses','leads','rooms','schedule_slots',
    'center_payments','record_edits','monthly_winners','financial_log','news'
  ]
  loop
    if exists (select 1 from information_schema.tables
               where table_schema='public' and table_name=t) then
      execute format('alter table public.%I enable row level security;', t);
      execute format('alter table public.%I force row level security;', t);
    end if;
  end loop;
end $$;

-- Eslatma: bu yerda hech qanday "create policy" yo'q — ataylab.
-- RLS yoqilgan, lekin policy yo'q => service-role'dan boshqa hech kim ko'rolmaydi.
