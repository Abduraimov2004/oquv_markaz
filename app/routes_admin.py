"""SUPER-ADMIN PANELI — faqat siz (tizim egasi). Barcha markazlarni ko'rasiz.

Bu yerda center_id filtri YO'Q — chunki superadmin hammasini boshqaradi.
"""
from datetime import date, timedelta, datetime
import calendar
import os

from fastapi import APIRouter, Request, Form, Depends, File, UploadFile
from fastapi.responses import RedirectResponse

from app.db import supabase
from app import data
from app.security import hash_password
from app.deps import norm_phone, templates, admin_required, _sys_get

router = APIRouter(prefix="/admin")


def _add_months_date(d: date, n: int) -> date:
    idx = d.year * 12 + (d.month - 1) + n
    y, m = idx // 12, idx % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _sub_state(su):
    """Obuna holati: none/expired/soon/ok + qolgan kun."""
    if not su:
        return "none", None
    try:
        d = date.fromisoformat(su[:10])
    except Exception:
        return "none", None
    days = (d - date.today()).days
    if days < 0:
        return "expired", days
    if days <= 7:
        return "soon", days
    return "ok", days


# ====================================================================
#  BOSH SAHIFA — butun biznes holati
# ====================================================================
@router.get("")
async def dashboard(request: Request, user: dict = Depends(admin_required)):
    centers = (
        supabase.table("centers")
        .select("id, name, owner_name, phone, status, subscription_until, created_at")
        .order("created_at", desc=True).execute().data
    ) or []

    students_total = supabase.table("students").select("id", count="exact").execute().count or 0
    teachers_total = supabase.table("teachers").select("id", count="exact").execute().count or 0

    # shu oydagi OBUNA tushumi (markazlardan)
    first_of_month = date.today().replace(day=1).isoformat()
    try:
        paid = (supabase.table("center_payments").select("amount")
                .gte("paid_at", first_of_month).execute().data) or []
        revenue = sum(float(p["amount"] or 0) for p in paid)
    except Exception:
        revenue = 0

    active = sum(1 for c in centers if c["status"] == "active")
    suspended = sum(1 for c in centers if c["status"] != "active")
    ending = []
    for c in centers:
        st, days = _sub_state(c.get("subscription_until"))
        c["sub_state"], c["days_left"] = st, days
        if st in ("expired", "soon"):
            ending.append(c)

    stats = {
        "centers": len(centers), "active": active, "suspended": suspended,
        "students": students_total, "teachers": teachers_total, "revenue": revenue,
    }
    return templates.TemplateResponse(
        "admin_dashboard.html",
        {"request": request, "user": user, "active": "dashboard",
         "stats": stats, "centers": centers[:8], "ending": ending[:8]},
    )


# ====================================================================
#  MARKAZLAR — ro'yxat + yangi markaz qo'shish (egasi bilan birga)
# ====================================================================
@router.get("/centers")
async def centers_page(request: Request, user: dict = Depends(admin_required)):
    centers = supabase.table("centers").select("*").order("created_at", desc=True).execute().data or []
    for c in centers:
        c["sub_state"], c["days_left"] = _sub_state(c.get("subscription_until"))
    return templates.TemplateResponse(
        "admin_centers.html",
        {"request": request, "user": user, "active": "centers",
         "centers": centers, "error": request.query_params.get("dup")},
    )


@router.post("/centers/add")
async def centers_add(
    request: Request, user: dict = Depends(admin_required),
    name: str = Form(...), owner_name: str = Form(""),
    owner_phone: str = Form(...), owner_password: str = Form(...),
    subscription_until: str = Form(""), monthly_fee: str = Form(""),
):
    owner_phone = owner_phone.strip()
    exists = supabase.table("users").select("id").eq("phone", owner_phone).limit(1).execute().data
    if exists:
        return RedirectResponse("/admin/centers?dup=1", status_code=303)
    try:
        fee = float(str(monthly_fee).replace(" ", "").replace(",", "")) if monthly_fee.strip() else 0
    except ValueError:
        fee = 0

    obj = {
        "name": name.strip(), "owner_name": owner_name.strip() or None,
        "phone": norm_phone(owner_phone), "status": "active",
        "subscription_until": subscription_until or None,
    }
    try:
        center = supabase.table("centers").insert(dict(obj, monthly_fee=fee)).execute().data[0]
    except Exception:
        center = supabase.table("centers").insert(obj).execute().data[0]

    supabase.table("users").insert({
        "center_id": center["id"], "role": "owner",
        "full_name": owner_name.strip() or None, "phone": norm_phone(owner_phone),
        "password_hash": hash_password(owner_password),
    }).execute()
    return RedirectResponse(f"/admin/centers/{center['id']}", status_code=303)


# ====================================================================
#  MARKAZ PANELI — to'liq boshqaruv (obuna, tahrir, parol, holat)
# ====================================================================
@router.get("/centers/{cid}")
async def center_detail(cid: str, request: Request, user: dict = Depends(admin_required)):
    rows = supabase.table("centers").select("*").eq("id", cid).limit(1).execute().data or []
    if not rows:
        return RedirectResponse("/admin/centers", status_code=303)
    center = rows[0]
    center["sub_state"], center["days_left"] = _sub_state(center.get("subscription_until"))

    owner = supabase.table("users").select("full_name, phone").eq("center_id", cid).eq("role", "owner").limit(1).execute().data or []
    owner = owner[0] if owner else {}

    counts = {}
    for tbl in ("students", "teachers", "groups"):
        try:
            counts[tbl] = supabase.table(tbl).select("id", count="exact").eq("center_id", cid).execute().count or 0
        except Exception:
            counts[tbl] = 0

    try:
        history = (supabase.table("center_payments").select("*").eq("center_id", cid)
                   .order("paid_at", desc=True).limit(30).execute().data) or []
    except Exception:
        history = []
    total_paid = sum(float(h["amount"] or 0) for h in history)

    branch_rows = data.branch_billing_rows(cid, center)
    center_fee = data.center_monthly_fee(cid, center)

    return templates.TemplateResponse("admin_center_detail.html", {
        "request": request, "user": user, "active": "centers",
        "center": center, "owner": owner, "counts": counts,
        "history": history, "total_paid": total_paid, "branch_rows": branch_rows,
        "center_fee": center_fee,
        "saved": request.query_params.get("saved"), "err": request.query_params.get("err"),
    })


@router.post("/centers/{cid}/edit")
async def center_edit(cid: str, request: Request, user: dict = Depends(admin_required),
                      name: str = Form(...), owner_name: str = Form(""),
                      owner_phone: str = Form(""), monthly_fee: str = Form("")):
    try:
        fee = float(str(monthly_fee).replace(" ", "").replace(",", "")) if monthly_fee.strip() else 0
    except ValueError:
        fee = 0
    upd = {"name": name.strip(), "owner_name": owner_name.strip() or None}
    if owner_phone.strip():
        upd["phone"] = norm_phone(owner_phone.strip())
    try:
        supabase.table("centers").update(dict(upd, monthly_fee=fee)).eq("id", cid).execute()
    except Exception:
        supabase.table("centers").update(upd).eq("id", cid).execute()
    # egasi loginini ham yangilaymiz
    o = {"full_name": owner_name.strip() or None}
    if owner_phone.strip():
        o["phone"] = norm_phone(owner_phone.strip())
    try:
        supabase.table("users").update(o).eq("center_id", cid).eq("role", "owner").execute()
    except Exception:
        pass
    return RedirectResponse(f"/admin/centers/{cid}?saved=1", status_code=303)


@router.post("/centers/{cid}/pay")
async def center_pay(cid: str, request: Request, user: dict = Depends(admin_required),
                     months: str = Form("1"), amount: str = Form(""), note: str = Form("")):
    rows = supabase.table("centers").select("*").eq("id", cid).limit(1).execute().data or []
    if not rows:
        return RedirectResponse("/admin/centers", status_code=303)
    c = rows[0]
    try:
        n = max(1, int(months))
    except ValueError:
        n = 1
    base = date.today()
    su = c.get("subscription_until")
    if su:
        try:
            d = date.fromisoformat(su[:10])
            if d > base:
                base = d
        except Exception:
            pass
    new_until = _add_months_date(base, n)
    fee = data.center_monthly_fee(cid, c)
    try:
        amt = float(str(amount).replace(" ", "").replace(",", "")) if amount.strip() else fee * n
    except ValueError:
        amt = fee * n

    err = ""
    try:
        supabase.table("center_payments").insert({
            "center_id": cid, "amount": amt, "months": n,
            "until": new_until.isoformat(), "note": note.strip() or None,
            "paid_at": datetime.now().isoformat(),
        }).execute()
    except Exception:
        err = "1"
    supabase.table("centers").update({"subscription_until": new_until.isoformat(), "status": "active"}).eq("id", cid).execute()
    return RedirectResponse(f"/admin/centers/{cid}?" + ("err=1" if err else "saved=1"), status_code=303)


@router.post("/centers/{cid}/password")
async def center_password(cid: str, request: Request, user: dict = Depends(admin_required), password: str = Form(...)):
    if password.strip():
        supabase.table("users").update({"password_hash": hash_password(password.strip())}).eq("center_id", cid).eq("role", "owner").execute()
    return RedirectResponse(f"/admin/centers/{cid}?saved=1", status_code=303)


@router.post("/centers/{cid}/toggle")
async def center_toggle(cid: str, request: Request, user: dict = Depends(admin_required)):
    rows = supabase.table("centers").select("status").eq("id", cid).limit(1).execute().data
    cur = rows[0]["status"] if rows else "active"
    new = "suspended" if cur == "active" else "active"
    supabase.table("centers").update({"status": new}).eq("id", cid).execute()
    return RedirectResponse(f"/admin/centers/{cid}", status_code=303)


@router.post("/centers/{cid}/force")
async def center_force(cid: str, request: Request, user: dict = Depends(admin_required)):
    """Obuna tugagan bo'lsa ham markaz ishlashda davom etsin (majburiy faol)."""
    rows = supabase.table("centers").select("force_active").eq("id", cid).limit(1).execute().data
    cur = bool(rows[0].get("force_active")) if rows else False
    supabase.table("centers").update({"force_active": (not cur)}).eq("id", cid).execute()
    return RedirectResponse(f"/admin/centers/{cid}", status_code=303)


# ====================================================================
#  💵 NARX SOZLAMALARI + FILIAL OBUNALARI
# ====================================================================
@router.post("/centers/{cid}/pricing")
async def center_pricing(cid: str, request: Request, user: dict = Depends(admin_required),
                         bill_base: str = Form("150000"), bill_per_student: str = Form("0"),
                         bill_per_teacher: str = Form("0")):
    def _num(x, d=0):
        try:
            return float(str(x).replace(" ", "").replace(",", "")) if str(x).strip() else d
        except ValueError:
            return d
    try:
        supabase.table("centers").update({
            "bill_base": _num(bill_base, 150000),
            "bill_per_student": _num(bill_per_student, 0),
            "bill_per_teacher": _num(bill_per_teacher, 0),
        }).eq("id", cid).execute()
    except Exception:
        pass
    return RedirectResponse(f"/admin/centers/{cid}?saved=1", status_code=303)


@router.post("/branches/{bid}/suspend")
async def branch_suspend(bid: str, request: Request, user: dict = Depends(admin_required)):
    """Filialni o'chirish/yoqish (ON/OFF)."""
    rows = supabase.table("branches").select("suspended, center_id").eq("id", bid).limit(1).execute().data or []
    cur = bool(rows[0].get("suspended")) if rows else False
    cdid = rows[0].get("center_id") if rows else ""
    supabase.table("branches").update({"suspended": (not cur)}).eq("id", bid).execute()
    return RedirectResponse(f"/admin/centers/{cdid}", status_code=303)


@router.post("/branches/{bid}/force")
async def branch_force(bid: str, request: Request, user: dict = Depends(admin_required)):
    """Obuna tugasa ham filial ishlasin (majburiy faol)."""
    rows = supabase.table("branches").select("force_active, center_id").eq("id", bid).limit(1).execute().data or []
    cur = bool(rows[0].get("force_active")) if rows else False
    cdid = rows[0].get("center_id") if rows else ""
    supabase.table("branches").update({"force_active": (not cur)}).eq("id", bid).execute()
    return RedirectResponse(f"/admin/centers/{cdid}", status_code=303)


@router.post("/branches/{bid}/extend")
async def branch_extend(bid: str, request: Request, user: dict = Depends(admin_required),
                        months: str = Form("1")):
    """Filial obunasini superadmin uzaytiradi (qo'lda)."""
    rows = supabase.table("branches").select("*").eq("id", bid).limit(1).execute().data or []
    if not rows:
        return RedirectResponse("/admin/centers", status_code=303)
    b = rows[0]
    try:
        n = max(1, int(months))
    except ValueError:
        n = 1
    base = date.today()
    su = b.get("sub_until")
    if su:
        try:
            d = date.fromisoformat(str(su)[:10])
            if d > base:
                base = d
        except Exception:
            pass
    new_until = _add_months_date(base, n)
    supabase.table("branches").update({"sub_until": new_until.isoformat(), "suspended": False}).eq("id", bid).execute()
    return RedirectResponse(f"/admin/centers/{b.get('center_id')}?saved=1", status_code=303)



@router.post("/centers/{cid}/delete")
async def center_delete(cid: str, request: Request, user: dict = Depends(admin_required)):
    try:
        supabase.table("users").delete().eq("center_id", cid).execute()
    except Exception:
        pass
    supabase.table("centers").delete().eq("id", cid).execute()
    return RedirectResponse("/admin/centers", status_code=303)


# ====================================================================
#  TO'LOV / OBUNA
# ====================================================================
@router.get("/subscription")
async def subscription_page(request: Request, user: dict = Depends(admin_required)):
    centers = supabase.table("centers").select(
        "id, name, status, subscription_until"
    ).order("created_at", desc=True).execute().data or []
    today = date.today().isoformat()
    soon = (date.today() + timedelta(days=7)).isoformat()
    for c in centers:
        su = c.get("subscription_until")
        if not su:
            c["sub_state"] = "none"
        elif su < today:
            c["sub_state"] = "expired"
        elif su <= soon:
            c["sub_state"] = "soon"
        else:
            c["sub_state"] = "ok"
    return templates.TemplateResponse("admin_subscription.html", {
        "request": request, "user": user, "active": "subscription", "centers": centers,
    })


@router.post("/subscription/{cid}/extend")
async def subscription_extend(cid: str, request: Request, user: dict = Depends(admin_required)):
    rows = supabase.table("centers").select("*").eq("id", cid).limit(1).execute().data
    base = date.today()
    fee = 0.0
    if rows:
        fee = float(rows[0].get("monthly_fee") or 0)
        su = rows[0].get("subscription_until")
        if su:
            try:
                cur = date.fromisoformat(su[:10])
                if cur > base:
                    base = cur
            except ValueError:
                pass
    new = _add_months_date(base, 1)
    try:
        supabase.table("center_payments").insert({
            "center_id": cid, "amount": fee, "months": 1, "until": new.isoformat(),
            "note": "Tezkor +1 oy", "paid_at": datetime.now().isoformat(),
        }).execute()
    except Exception:
        pass
    supabase.table("centers").update({"subscription_until": new.isoformat(), "status": "active"}).eq("id", cid).execute()
    return RedirectResponse("/admin/subscription", status_code=303)


@router.post("/subscription/{cid}/toggle")
async def subscription_toggle(cid: str, request: Request, user: dict = Depends(admin_required)):
    rows = supabase.table("centers").select("status").eq("id", cid).limit(1).execute().data
    cur = rows[0]["status"] if rows else "active"
    new = "suspended" if cur == "active" else "active"
    supabase.table("centers").update({"status": new}).eq("id", cid).execute()
    return RedirectResponse("/admin/subscription", status_code=303)


# ====================================================================
#  TIZIM SOG'LIG'I
# ====================================================================
@router.get("/health")
async def health_page(request: Request, user: dict = Depends(admin_required)):
    import platform
    import sys

    db_ok = True
    counts = {}
    try:
        for tbl in ["centers", "users", "teachers", "groups", "students",
                    "parents", "attendance", "grades", "lessons", "payments"]:
            counts[tbl] = supabase.table(tbl).select("id", count="exact").execute().count or 0
    except Exception:
        db_ok = False

    info = {
        "python": sys.version.split()[0],
        "platform": platform.system(),
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    res = None
    try:
        import psutil
        res = {"cpu": psutil.cpu_percent(interval=0.3), "ram": psutil.virtual_memory().percent}
    except Exception:
        res = None

    return templates.TemplateResponse("admin_health.html", {
        "request": request, "user": user, "active": "health",
        "db_ok": db_ok, "counts": counts, "info": info, "res": res,
    })


# ====================================================================
#  YANGILIKLAR
# ====================================================================
@router.get("/news")
async def news_page(request: Request, user: dict = Depends(admin_required)):
    news = supabase.table("news").select("*").order("created_at", desc=True).execute().data or []
    return templates.TemplateResponse("admin_news.html", {
        "request": request, "user": user, "active": "news", "news": news,
    })


@router.post("/news/add")
async def news_add(request: Request, user: dict = Depends(admin_required),
                   title: str = Form(...), body: str = Form(""), expires_at: str = Form("")):
    obj = {"title": title.strip(), "body": body.strip() or None}
    if expires_at.strip():
        obj["expires_at"] = expires_at.strip()
    try:
        supabase.table("news").insert(obj).execute()
    except Exception:
        supabase.table("news").insert({"title": obj["title"], "body": obj.get("body")}).execute()
    return RedirectResponse("/admin/news", status_code=303)


@router.post("/news/{nid}/delete")
async def news_delete(nid: str, request: Request, user: dict = Depends(admin_required)):
    supabase.table("news").delete().eq("id", nid).execute()
    return RedirectResponse("/admin/news", status_code=303)


# ====================================================================
#  TIZIM SOZLAMALARI — superadmin uchun
# ====================================================================
def _sys_save(data: dict):
    """system_settings (id=1) ni yangilaydi (bo'lmasa yaratadi)."""
    try:
        supabase.table("system_settings").update({"data": data}).eq("id", 1).execute()
    except Exception:
        try:
            supabase.table("system_settings").insert({"id": 1, "data": data}).execute()
        except Exception:
            pass


@router.get("/settings")
async def admin_settings(request: Request, user: dict = Depends(admin_required)):
    s = _sys_get()
    return templates.TemplateResponse("admin_settings.html", {
        "request": request, "user": user, "active": "settings",
        "s": s, "saved": request.query_params.get("saved"),
    })


@router.post("/settings")
async def admin_settings_save(
    request: Request, user: dict = Depends(admin_required),
    brand_name: str = Form(""), support_phone: str = Form(""),
    support_telegram: str = Form(""), default_fee: str = Form(""),
    logo: UploadFile = File(None),
):
    s = dict(_sys_get())
    s["brand_name"] = brand_name.strip()
    s["support_phone"] = support_phone.strip()
    s["support_telegram"] = support_telegram.strip()
    try:
        s["default_fee"] = float(str(default_fee).replace(" ", "").replace(",", ".")) if default_fee.strip() else 0
    except ValueError:
        s["default_fee"] = 0

    # Tizim logosi
    if logo is not None and getattr(logo, "filename", ""):
        ext = os.path.splitext(logo.filename)[1].lower()
        if ext in (".png", ".jpg", ".jpeg", ".webp", ".svg"):
            try:
                os.makedirs("app/static/uploads", exist_ok=True)
                fname = f"system_logo{ext}"
                content = await logo.read()
                if content:
                    with open(f"app/static/uploads/{fname}", "wb") as f:
                        f.write(content)
                    import time as _t
                    s["logo_url"] = f"/static/uploads/{fname}?v={int(_t.time())}"
            except Exception:
                pass

    _sys_save(s)
    return RedirectResponse("/admin/settings?saved=1", status_code=303)
