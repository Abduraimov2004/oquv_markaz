"""Supabase ulanishi — butun loyiha shu bitta klientni ishlatadi.

DIQQAT: bu yerda SERVICE_ROLE kaliti ishlatiladi. U RLS'ni chetlab o'tadi,
shuning uchun bu klientni FAQAT server tomonida ishlating, hech qachon
frontendga (brauzerga) yubormang. Markazlar izolatsiyasi har bir so'rovda
`.eq("center_id", ...)` orqali kod darajasida ta'minlanadi.
"""
from supabase import create_client, Client
from app.config import settings

supabase: Client = create_client(
    settings.SUPABASE_URL,
    settings.SUPABASE_SERVICE_KEY,
)
