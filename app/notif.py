"""Ichki bildirishnomalar markazi — filialga bog'langan."""
from datetime import datetime

from app.db import supabase


def _visible(n, bid):
    """Filial tanlangan bo'lsa — faqat o'sha filial bildirishnomasi (aralashmaydi).
    Filialsiz markaz (bid yo'q) — hammasi ko'rinadi."""
    if not bid:
        return True
    return n.get("branch_id") == bid


def notify(cid: str, title: str, body: str = "", kind: str = "info", branch_id=None):
    if not cid or not title:
        return
    obj = {"center_id": cid, "title": title, "body": body or None, "kind": kind}
    if branch_id:
        obj["branch_id"] = branch_id
    try:
        supabase.table("notifications").insert(obj).execute()
    except Exception:
        obj.pop("branch_id", None)
        try:
            supabase.table("notifications").insert(obj).execute()
        except Exception:
            pass


def unread_count(cid: str, branch_id=None) -> int:
    if not cid:
        return 0
    try:
        rows = supabase.table("notifications").select("read_at, branch_id").eq("center_id", cid).execute().data or []
        return sum(1 for r in rows if not r.get("read_at") and _visible(r, branch_id))
    except Exception:
        return 0


def recent(cid: str, branch_id=None, limit: int = 60):
    try:
        rows = supabase.table("notifications").select("*").eq("center_id", cid).order("created_at", desc=True).limit(200).execute().data or []
        return [r for r in rows if _visible(r, branch_id)][:limit]
    except Exception:
        return []


def mark_all_read(cid: str, branch_id=None):
    try:
        rows = supabase.table("notifications").select("id, read_at, branch_id").eq("center_id", cid).execute().data or []
        now = datetime.now().isoformat()
        for r in rows:
            if not r.get("read_at") and _visible(r, branch_id):
                supabase.table("notifications").update({"read_at": now}).eq("id", r["id"]).execute()
    except Exception:
        pass
