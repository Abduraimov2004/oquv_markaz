"""Umumiy yordamchilar: shablonlar, kim kirgani, rol tekshiruvi.

Sessiyada `request.session["user"]` saqlanadi:
    {"id": ..., "role": "owner"|"superadmin", "center_id": ..., "name": ...}
"""
from datetime import date

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.db import supabase


# Administratorga berilishi mumkin bo'lgan panellar (owner galochka qo'yadi)
PANELS = [
    ("dashboard", "Bosh sahifa"),
    ("students", "O'quvchilar"),
    ("groups", "Guruhlar"),
    ("waitlist", "Navbat"),
    ("risk", "Ketish xavfi"),
    ("leads", "Lidlar (CRM)"),
    ("schedule", "Dars jadvali"),
    ("payments", "To'lovlar"),
    ("reports", "Hisobotlar"),
    ("teachers", "O'qituvchilar"),
    ("announce", "E'lon"),
    ("cashbox", "Kassa"),
    ("earnings", "Maoshlar"),
    ("monitoring", "O'qituvchi nazorati"),
    ("coins", "Coin tizimi"),
    ("notifications", "Bildirishnomalar"),
    ("expense_requests", "Xarajat so'rovlari"),
    ("analytics", "Analitika"),
    ("holidays", "Bayram kunlari"),
    ("branches", "Filiallar"),
]
GRANTABLE = {k for k, _ in PANELS}


def _panel_key(path: str) -> str:
    """URL -> panel kaliti (reception ruxsatini tekshirish uchun)."""
    p = path[len("/owner"):] if path.startswith("/owner") else path
    p = p.strip("/")
    if not p:
        return "dashboard"
    seg = p.split("/")[0]
    aliases = {"rooms": "schedule"}
    return aliases.get(seg, seg)


def _load_perms(uid: str) -> set:
    try:
        rows = supabase.table("users").select("permissions").eq("id", uid).limit(1).execute().data or []
        raw = (rows[0].get("permissions") if rows else "") or ""
        return {x.strip() for x in raw.split(",") if x.strip()}
    except Exception:
        return set()


def _sys_get() -> dict:
    """Tizim (superadmin) sozlamalari — JSON. Migratsiya yo'q bo'lsa bo'sh."""
    try:
        rows = supabase.table("system_settings").select("data").eq("id", 1).limit(1).execute().data or []
        return (rows[0].get("data") if rows else {}) or {}
    except Exception:
        return {}


def _center_info(cid):
    if not cid:
        return {}
    try:
        rows = supabase.table("centers").select(
            "name, status, subscription_until, force_active, logo_url"
        ).eq("id", cid).limit(1).execute().data or []
        return rows[0] if rows else {}
    except Exception:
        # Eski bazada (v17 migratsiyasi run qilinmagan) ustunlar bo'lmasligi mumkin
        try:
            rows = supabase.table("centers").select(
                "name, status, subscription_until"
            ).eq("id", cid).limit(1).execute().data or []
            return rows[0] if rows else {}
        except Exception:
            return {}


def _center_block_reason(c) -> str | None:
    """Markazga kirish to'siqmi? None=ruxsat, 'suspended'=admin to'xtatgan,
    'expired'=obuna tugagan. Admin 'force_active' qo'ysa obuna tugasa ham ishlaydi."""
    if not c:
        return None
    # Admin qo'lda to'xtatgan bo'lsa — har doim bloklangan
    if c.get("status") and c["status"] != "active":
        return "suspended"
    # Admin "obuna tugasa ham ishlasin" deb belgilagan bo'lsa — ruxsat
    if c.get("force_active"):
        return None
    # Obuna sanasi o'tib ketgan bo'lsa — to'xtatiladi
    su = c.get("subscription_until")
    if su:
        try:
            if date.fromisoformat(str(su)[:10]) < date.today():
                return "expired"
        except Exception:
            pass
    return None


# Yangi Starlette TemplateResponse(request, name, context) tartibini talab qiladi.
# Marshrutlarimiz eski (name, context) uslubida yozilgan — bu kichik moslashtiruvchi
# ikkalasini ham qo'llab-quvvatlaydi, shunda hech qaysi marshrutni o'zgartirmaymiz.
class _Templates(Jinja2Templates):
    def TemplateResponse(self, *args, **kwargs):
        # Eski uslub: birinchi argument satr (shablon nomi) bo'lsa
        if args and isinstance(args[0], str):
            name = args[0]
            context = args[1] if len(args) > 1 else kwargs.pop("context", {})
            request = context.get("request")
            return super().TemplateResponse(request, name, context, **kwargs)
        # Yangi uslub: o'zgartirmasdan o'tkazamiz
        return super().TemplateResponse(*args, **kwargs)


templates = _Templates(directory="app/templates")


class AuthRedirect(Exception):
    """Kirilmagan/ruxsati yo'q bo'lsa /login ga yo'naltirish uchun."""
    def __init__(self, to: str = "/login"):
        self.to = to


def current_user(request: Request):
    """Sessiyadagi foydalanuvchini qaytaradi (yoki None) — slot bo'yicha."""
    slot = getattr(request.state, "cslot", "0")
    if slot == "0":
        return request.session.get("user")
    return (request.session.get("slots") or {}).get(slot)


def set_user(request: Request, user: dict):
    slot = getattr(request.state, "cslot", "0")
    if slot == "0":
        request.session["user"] = user
    else:
        slots = request.session.get("slots") or {}
        slots[slot] = user
        request.session["slots"] = slots


def clear_user(request: Request):
    slot = getattr(request.state, "cslot", "0")
    if slot == "0":
        request.session.pop("user", None)
    else:
        slots = request.session.get("slots") or {}
        slots.pop(slot, None)
        request.session["slots"] = slots


def active_branch(request: Request, cid):
    """Tanlangan filial id (yoki None = barcha filiallar)."""
    return (request.session.get("branch") or {}).get(str(cid))


def set_active_branch(request: Request, cid, bid):
    b = dict(request.session.get("branch") or {})
    if bid:
        b[str(cid)] = bid
    else:
        b.pop(str(cid), None)
    request.session["branch"] = b


def _staff_guard(request: Request, allow: tuple) -> dict:
    user = current_user(request)
    if not user:
        raise AuthRedirect()
    role = user.get("role")
    if role not in allow:
        # tizimga kirgan, lekin bu sahifaga roli yetmaydi
        if role in ("owner", "reception"):
            raise AuthRedirect("/owner?denied=1")
        raise AuthRedirect()
    c = _center_info(user.get("center_id"))
    reason = _center_block_reason(c)
    if reason:
        clear_user(request)
        raise AuthRedirect(f"/login?{reason}=1")
    user = dict(user)
    user["center_name"] = c.get("name")
    user["center_logo"] = c.get("logo_url")
    user["is_owner"] = (role == "owner")
    try:
        from app import notif as _notif
        user["notif_unread"] = _notif.unread_count(user.get("center_id"))
    except Exception:
        user["notif_unread"] = 0
    # 🏢 Filiallar — ro'yxat + tanlangan filial
    cid2 = user.get("center_id")
    try:
        brs = supabase.table("branches").select("id, name").eq("center_id", cid2).order("name").execute().data or []
    except Exception:
        brs = []
    bid = active_branch(request, cid2)
    if bid and not any(b["id"] == bid for b in brs):
        bid = None
    user["branches"] = brs
    user["active_branch"] = bid
    user["active_branch_name"] = next((b["name"] for b in brs if b["id"] == bid), None)
    if role == "reception":
        perms = _load_perms(user.get("id"))
        user["perms"] = perms
        key = _panel_key(request.url.path)
        if key != "dashboard" and key in GRANTABLE and key not in perms:
            raise AuthRedirect("/owner?denied=1")
    return user


def owner_required(request: Request) -> dict:
    """Faqat markaz egasi (owner)."""
    return _staff_guard(request, ("owner",))


def staff_required(request: Request) -> dict:
    """Markaz egasi yoki administrator (reception)."""
    return _staff_guard(request, ("owner", "reception"))


def admin_required(request: Request) -> dict:
    """Faqat superadmin (tizim egasi) kira oladigan sahifalar uchun."""
    user = current_user(request)
    if not user or user.get("role") != "superadmin":
        raise AuthRedirect()
    sys = _sys_get()
    user = dict(user)
    user["center_name"] = sys.get("brand_name") or None
    user["center_logo"] = sys.get("logo_url") or None
    return user


def teacher_required(request: Request) -> dict:
    """Faqat o'qituvchi kira oladigan sahifalar uchun."""
    user = current_user(request)
    if not user or user.get("role") != "teacher":
        raise AuthRedirect()
    c = _center_info(user.get("center_id"))
    reason = _center_block_reason(c)
    if reason:
        clear_user(request)
        raise AuthRedirect(f"/login?{reason}=1")
    user = dict(user)
    user["center_name"] = c.get("name")
    user["center_logo"] = c.get("logo_url")
    return user


def norm_phone(p: str) -> str:
    """Telefon raqamini bir xil ko'rinishga keltiradi (probel, chiziqcha, qavslarni olib tashlaydi).
    Login va saqlashda ishlatiladi — format farqi tufayli kira olmaslik muammosini bartaraf etadi."""
    if not p:
        return p
    return "".join(ch for ch in p if ch.isdigit() or ch == "+").strip()
