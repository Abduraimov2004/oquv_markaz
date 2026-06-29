"""O'quv markaz platformasi — web backend (FastAPI).

Ishga tushirish:  uvicorn app.main:app --reload
"""
from fastapi import FastAPI, Request, Form
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.db import supabase
from app.security import verify_password
from app.deps import templates, current_user, AuthRedirect, set_user, clear_user, norm_phone
from app.routes_owner import router as owner_router
from app.routes_admin import router as admin_router
from app.routes_teacher import router as teacher_router

app = FastAPI(title="O'quv Markaz Platformasi")

# Yuklangan rasmlar (o'quvchi fotosi) uchun static papka
import os as _os
from fastapi.staticfiles import StaticFiles
_os.makedirs("app/static/uploads", exist_ok=True)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Sessiya (imzolangan cookie) — login holatini saqlaydi
app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY)

from app.multitenant import MultiTenantMiddleware
app.add_middleware(MultiTenantMiddleware)


# Ruxsat yo'q bo'lsa -> login sahifasiga yo'naltirish
@app.exception_handler(AuthRedirect)
async def _auth_redirect_handler(request: Request, exc: AuthRedirect):
    return RedirectResponse(exc.to, status_code=303)


# --------------------------------------------------------------------
#  BOSH SAHIFA — rolga qarab yo'naltirish
# --------------------------------------------------------------------
@app.get("/")
async def root(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if user["role"] == "superadmin":
        return RedirectResponse("/admin", status_code=303)
    if user["role"] == "teacher":
        return RedirectResponse("/teacher", status_code=303)
    return RedirectResponse("/owner", status_code=303)


# --------------------------------------------------------------------
#  LOGIN / LOGOUT
# --------------------------------------------------------------------
@app.get("/login")
async def login_page(request: Request):
    err = None
    if request.query_params.get("suspended"):
        err = "Markaz vaqtincha to'xtatilgan. Tizim egasiga murojaat qiling."
    return templates.TemplateResponse("login.html", {
        "request": request, "error": err, "current": current_user(request),
    })


@app.post("/login")
async def login_submit(request: Request, phone: str = Form(...), password: str = Form(...)):
    phone = norm_phone(phone.strip())
    # Telefon raqami bo'yicha foydalanuvchini topamiz
    res = (
        supabase.table("users")
        .select("*")
        .eq("phone", phone)
        .eq("is_active", True)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    user = rows[0] if rows else None

    if user and verify_password(password, user["password_hash"]):
        if user.get("role") == "owner" and user.get("center_id"):
            crows = supabase.table("centers").select("status").eq("id", user["center_id"]).limit(1).execute().data or []
            if crows and crows[0].get("status") and crows[0]["status"] != "active":
                return templates.TemplateResponse("login.html", {
                    "request": request,
                    "error": "Markaz vaqtincha to'xtatilgan. Tizim egasiga murojaat qiling.",
                }, status_code=403)
        set_user(request, {
            "id": user["id"],
            "role": user["role"],
            "center_id": user.get("center_id"),
            "name": user.get("full_name") or phone,
        })
        return RedirectResponse((getattr(request.state, "cprefix", "") or "") + "/", status_code=303)

    # users'da topilmadi -> o'qituvchi (teachers) jadvalini tekshiramiz
    try:
        trows = (
            supabase.table("teachers")
            .select("id, full_name, center_id, password_hash")
            .eq("phone", phone).execute().data
        ) or []
    except Exception:
        trows = []  # password_hash ustuni hali yo'q bo'lsa (schema_v4 RUN qilinmagan)
    for t in trows:
        if t.get("password_hash") and verify_password(password, t["password_hash"]):
            if t.get("center_id"):
                crows = supabase.table("centers").select("status").eq("id", t["center_id"]).limit(1).execute().data or []
                if crows and crows[0].get("status") and crows[0]["status"] != "active":
                    return templates.TemplateResponse("login.html", {
                        "request": request,
                        "error": "Markaz vaqtincha to'xtatilgan. Tizim egasiga murojaat qiling.",
                    }, status_code=403)
            set_user(request, {
                "id": t["id"],
                "role": "teacher",
                "center_id": t.get("center_id"),
                "name": t.get("full_name") or phone,
            })
            return RedirectResponse((getattr(request.state, "cprefix", "") or "") + "/", status_code=303)

    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": "Telefon yoki parol noto'g'ri."},
        status_code=401,
    )


@app.get("/logout")
async def logout(request: Request):
    clear_user(request)
    return RedirectResponse((getattr(request.state, "cprefix", "") or "") + "/login", status_code=303)


# Panel marshrutlarini ulaymiz
app.include_router(owner_router)
app.include_router(admin_router)
app.include_router(teacher_router)


# ====================================================================
#  OTA-ONA KABINETI — ommaviy, login talab qilmaydi (maxfiy token)
#  /p/{token} — farzandi davomati, baholari va to'lovini ko'rsatadi.
# ====================================================================
from app import data as _data


@app.get("/p/{token}")
async def parent_cabinet(token: str, request: Request):
    try:
        srows = supabase.table("students").select("*").eq("access_token", token).limit(1).execute().data or []
    except Exception:
        srows = []
    if not srows:
        return templates.TemplateResponse("parent_cabinet.html", {"request": request, "ok": False}, status_code=404)
    s = srows[0]
    cid, sid = s["center_id"], s["id"]
    crow = supabase.table("centers").select("name").eq("id", cid).limit(1).execute().data or []
    center_name = crow[0]["name"] if crow else "O'quv markaz"
    groups = {g["id"]: g for g in (supabase.table("groups").select("id, name, subject, monthly_fee").eq("center_id", cid).execute().data or [])}

    # To'lov / qarz — fan bo'yicha
    pf = _data.pair_fees(cid)
    paid = _data.paid_total_by_pair(cid)
    starts = _data.enrollment_starts(cid)
    now = _data.cur_ym()
    subjects = []
    total_debt = 0.0
    for (xsid, gid), fee in pf.items():
        if xsid != sid:
            continue
        summ = _data.pair_summary(starts.get((xsid, gid)) or now, now, fee, paid.get((xsid, gid), 0.0))
        g = groups.get(gid, {})
        subjects.append({"name": g.get("name") or g.get("subject") or "Fan",
                         "fee": fee, "debt": summ["debt"], "ahead": summ["ahead"]})
        total_debt += summ["debt"]

    # Davomat (umumiy)
    att = supabase.table("attendance").select("status").eq("student_id", sid).execute().data or []
    present = sum(1 for a in att if a.get("status") in ("present", "late"))
    total_att = len(att)
    att_rate = round(present * 100 / total_att) if total_att else None

    # Oxirgi baholar
    grows = (supabase.table("grades").select("grade, comment, date, group_id")
             .eq("student_id", sid).order("date", desc=True).limit(12).execute().data) or []
    grades = [{"grade": g.get("grade"), "comment": g.get("comment"),
               "date": (g.get("date") or "")[:10],
               "subject": (groups.get(g.get("group_id"), {}) or {}).get("name", "")} for g in grows]

    return templates.TemplateResponse("parent_cabinet.html", {
        "request": request, "ok": True, "student": s, "center_name": center_name,
        "subjects": subjects, "total_debt": total_debt,
        "present": present, "total_att": total_att, "att_rate": att_rate,
        "grades": grades,
    })
