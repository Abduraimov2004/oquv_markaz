"""Moliyaviy audit — to'lov / xarajat / o'qituvchi oyligi bo'yicha o'zgarishlar izi.

Pul bilan bog'liq har bir amal (qo'shildi/o'chirildi) shu yerga yoziladi.
Agar `financial_log` jadvali hali yaratilmagan bo'lsa — jim o'tadi (sahifa qulamaydi).
"""
from app.db import supabase


def log_financial(center_id, kind, action, amount=0, actor=None, ref_id=None, note=None):
    """kind: 'payment' | 'expense' | 'payout'
       action: 'create' | 'delete'
       actor: {'role':..., 'id':..., 'name':...} (kim bajardi)"""
    try:
        supabase.table("financial_log").insert({
            "center_id": center_id,
            "kind": kind,
            "action": action,
            "amount": float(amount or 0),
            "actor_role": (actor or {}).get("role"),
            "actor_id": (actor or {}).get("id"),
            "actor_name": (actor or {}).get("name"),
            "ref_id": str(ref_id) if ref_id else None,
            "note": note,
        }).execute()
    except Exception:
        pass
