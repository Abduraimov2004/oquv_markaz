-- =====================================================================
--  schema_v14 — navbat (waitlist) yaxshilanishi
--  Navbatdagi yozuvni mavjud o'quvchiga yoki CRM lidiga bog'lash.
--  Supabase -> SQL Editor -> RUN (qayta ishlatsa ham xavfsiz).
-- =====================================================================

alter table waitlist add column if not exists student_id uuid references students(id) on delete set null;
alter table waitlist add column if not exists lead_id    uuid references leads(id)    on delete set null;
