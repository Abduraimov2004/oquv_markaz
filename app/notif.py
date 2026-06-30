"""Ichki bildirishnomalar markazi yordamchilari."""
from datetime import datetime

from app.db import supabase


def notify(cid: str, title: str, body: str = "", kind: str = "info"):
    """Markaz uchun bildirishnoma yaratadi. Jadval bo'lmasa jim o'tadi."""
    if not cid or not title:
        return
    try:
        supabase.table("notifications").insert({
            "center_id": cid, "title": title,
            "body": body or None, "kind": kind,
        }).execute()
    except Exception:
        pass


def unread_count(cid: str) -> int:
    if not cid:
        return 0
    try:
        rows = supabase.table("notifications").select("read_at").eq("center_id", cid).execute().data or []
        return sum(1 for r in rows if not r.get("read_at"))
    except Exception:
        return 0


def recent(cid: str, limit: int = 60):
    try:
        return supabase.table("notifications").select("*").eq("center_id", cid).order("created_at", desc=True).limit(limit).execute().data or []
    except Exception:
        return []


def mark_all_read(cid: str):
    try:
        rows = supabase.table("notifications").select("id, read_at").eq("center_id", cid).execute().data or []
        now = datetime.now().isoformat()
        for r in rows:
            if not r.get("read_at"):
                supabase.table("notifications").update({"read_at": now}).eq("id", r["id"]).execute()
    except Exception:
        pass
