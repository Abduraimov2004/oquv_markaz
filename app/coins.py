"""Coin (gamifikatsiya) tizimi yordamchilari.

Qoidalar centers.settings["coins"] JSON ichida saqlanadi.
Tranzaksiyalar coin_tx jadvalida (+ topildi, - sarflandi).
"""
from app.db import supabase

DEFAULT_RULES = {
    "attendance": 5,    # darsga kelganda
    "homework": 3,      # uy vazifasi
    "test70": 8,        # test 70-89 ball
    "test90": 15,       # test 90+ ball
    "ontime": 20,       # o'z vaqtida to'lov
    "value": 100,       # 1 coin = necha so'm
    "enabled": True,
}


def rules(cid: str) -> dict:
    try:
        rows = supabase.table("centers").select("settings").eq("id", cid).limit(1).execute().data or []
        s = (rows[0].get("settings") if rows else {}) or {}
        c = dict(DEFAULT_RULES)
        c.update(s.get("coins") or {})
        return c
    except Exception:
        return dict(DEFAULT_RULES)


def save_rules(cid: str, new_rules: dict):
    rows = supabase.table("centers").select("settings").eq("id", cid).limit(1).execute().data or []
    s = dict((rows[0].get("settings") if rows else {}) or {})
    s["coins"] = new_rules
    supabase.table("centers").update({"settings": s}).eq("id", cid).execute()


def is_enabled(cid: str) -> bool:
    return bool(rules(cid).get("enabled", True))


def award(cid: str, student_id: str, amount: int, reason: str, note: str = ""):
    """Coin qo'shadi (manfiy bo'lsa — sarflaydi). Jadval bo'lmasa jim o'tadi."""
    try:
        amount = int(amount)
    except Exception:
        return
    if not amount or not student_id:
        return
    try:
        supabase.table("coin_tx").insert({
            "center_id": cid, "student_id": student_id,
            "amount": amount, "reason": reason, "note": note or None,
        }).execute()
    except Exception:
        pass


def award_rule(cid: str, student_id: str, rule_key: str, note: str = ""):
    """Qoidaga ko'ra coin beradi (coin tizimi yoqilgan bo'lsa)."""
    r = rules(cid)
    if not r.get("enabled", True):
        return
    amt = int(r.get(rule_key) or 0)
    if amt > 0:
        award(cid, student_id, amt, rule_key, note)


def balance(student_id: str) -> int:
    try:
        rows = supabase.table("coin_tx").select("amount").eq("student_id", student_id).execute().data or []
        return sum(int(x.get("amount") or 0) for x in rows)
    except Exception:
        return 0


def balances_for_center(cid: str) -> dict:
    out = {}
    try:
        rows = supabase.table("coin_tx").select("student_id, amount").eq("center_id", cid).execute().data or []
        for r in rows:
            out[r["student_id"]] = out.get(r["student_id"], 0) + int(r.get("amount") or 0)
    except Exception:
        pass
    return out


def recent_tx(cid: str, limit: int = 40):
    try:
        return supabase.table("coin_tx").select("*").eq("center_id", cid).order("created_at", desc=True).limit(limit).execute().data or []
    except Exception:
        return []


def stats(cid: str) -> dict:
    """Jami topilgan / sarflangan / aktiv balans."""
    earned = spent = 0
    try:
        rows = supabase.table("coin_tx").select("amount").eq("center_id", cid).execute().data or []
        for r in rows:
            a = int(r.get("amount") or 0)
            if a >= 0:
                earned += a
            else:
                spent += -a
    except Exception:
        pass
    return {"earned": earned, "spent": spent, "active": earned - spent}
