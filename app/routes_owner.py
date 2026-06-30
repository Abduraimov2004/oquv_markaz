"""MARKAZ EGASI PANELI — multi-tenant (center_id), ko'p fanli model.

O'quvchi bir nechta fanga (guruhga) yozilishi mumkin — qatnashuv (enrollments)
orqali. To'lov har fan uchun alohida. O'qituvchi foizi — o'qituvchiga bog'liq.
"""
from datetime import date, datetime, timedelta
import calendar

from fastapi import APIRouter, Request, Form, Depends, File, UploadFile
from fastapi.responses import RedirectResponse

from app.db import supabase
from app.deps import templates, owner_required, staff_required, PANELS, norm_phone, set_active_branch
from app import data
from app import coins as coinmod
from app import notif as notifmod
from app.notify import notify_parent
from app.security import hash_password

router = APIRouter(prefix="/owner")


_KIND2METHOD = {"cash": "naqd", "card": "karta", "click": "click", "payme": "payme", "other": "o'tkazma"}


def _acc_method(account_id: str) -> str:
    """Hisob turidan to'lov usulini aniqlaydi (naqd/karta/...)."""
    if not account_id:
        return ""
    try:
        rows = supabase.table("accounts").select("kind").eq("id", account_id).limit(1).execute().data or []
        if rows:
            return _KIND2METHOD.get(rows[0].get("kind") or "cash", "naqd")
    except Exception:
        pass
    return ""


def _insert_payment(base: dict, group_id="", account_id="", method="") -> bool:
    """To'lovni qatlamli (graceful) qo'shadi — yangi ustunlar bo'lmasa ham ishlaydi."""
    if account_id and not method:
        method = _acc_method(account_id)   # hisob turidan usulni aniqlaymiz
    full = dict(base)
    if group_id:
        full["group_id"] = group_id
    if account_id:
        full["account_id"] = account_id
    if method:
        full["method"] = method
    attempts = [full]
    if account_id or method:
        mid = dict(base)
        if group_id:
            mid["group_id"] = group_id
        attempts.append(mid)
    attempts.append(dict(base))
    for a in attempts:
        try:
            supabase.table("payments").insert(a).execute()
            return True
        except Exception:
            continue
    return False


def _insufficient(cid: str, account_id: str, amount: float):
    """Tanlangan hisobda mablag' yetarli emasligini tekshiradi.
    (yetarli emas bo'lsa) -> (True, balans). Aks holda (False, balans)."""
    if not account_id:
        return False, None
    try:
        bal = data.account_balances(cid).get(account_id)
    except Exception:
        bal = None
    if bal is None:
        return False, None
    return (amount > bal + 0.001), bal


def _insert_outflow(table: str, base: dict, account_id="", method="") -> bool:
    """Chiqim (xarajat/maosh/obuna) — account/method bilan, graceful."""
    full = dict(base)
    if account_id:
        full["account_id"] = account_id
    if method:
        full["method"] = method
    for a in ([full, dict(base)] if (account_id or method) else [dict(base)]):
        try:
            supabase.table(table).insert(a).execute()
            return True
        except Exception:
            continue
    return False


def _center_settings(cid: str) -> dict:
    try:
        rows = supabase.table("centers").select("name, settings, logo_url").eq("id", cid).limit(1).execute().data
    except Exception:
        # logo_url ustuni hali yo'q (migratsiya run qilinmagan) — yiqilmaymiz
        rows = supabase.table("centers").select("name, settings").eq("id", cid).limit(1).execute().data
    if not rows:
        return {"name": "", "settings": {}}
    return rows[0]


# ====================================================================
#  BOSH SAHIFA
# ====================================================================
@router.get("")
async def dashboard(request: Request, user: dict = Depends(staff_required)):
    cid = user["center_id"]
    today = date.today().isoformat()

    students_all = supabase.table("students").select("*").eq("center_id", cid).execute().data or []
    students_all = _bfilter(students_all, user.get("active_branch"))
    students = [s for s in students_all if s.get("active", True) is not False]
    groups = supabase.table("groups").select(
        "id, name, subject, teacher_id, schedule_days, schedule_time, branch_id"
    ).eq("center_id", cid).order("created_at", desc=True).execute().data or []
    groups = _bfilter(groups, user.get("active_branch"))
    teachers = supabase.table("teachers").select("id, full_name, branch_id").eq("center_id", cid).execute().data or []
    teachers = _bfilter(teachers, user.get("active_branch"))
    attendance_today = supabase.table("attendance").select("student_id, status").eq("center_id", cid).eq("date", today).execute().data or []

    sname = {s["id"]: s["full_name"] for s in students_all}
    tname = {t["id"]: t["full_name"] for t in teachers}
    enr = data.center_enrollments(cid)
    per_group = {}
    for e in enr:
        per_group[e["group_id"]] = per_group.get(e["group_id"], 0) + 1

    present = len({a["student_id"] for a in attendance_today if a["status"] in ("present", "late")})
    absent = max(0, len(students) - present)

    # To'lov qarzi — oylik model bo'yicha (joriy oy holatiga)
    now_ym = data.cur_ym()
    pf = data.pair_fees(cid)
    paid_total = data.paid_total_by_pair(cid)
    starts = data.enrollment_starts(cid)
    active_ids = {s["id"] for s in students}
    attention = []
    debtor_count = 0
    total_debt = 0.0
    for e in enr:
        sid, gid = e["student_id"], e["group_id"]
        if sid not in active_ids:
            continue
        fee = pf.get((sid, gid), 0) or 0
        if fee <= 0:
            continue
        summ = data.pair_summary(starts.get((sid, gid)) or now_ym, now_ym, fee, paid_total.get((sid, gid), 0.0))
        if summ["debt"] > 0:
            debtor_count += 1
            total_debt += summ["debt"]
            attention.append({"name": sname.get(sid, "—"),
                              "reason": f"Qarz: {int(summ['debt']):,} so'm".replace(",", " ")})
    attention.sort(key=lambda a: a["name"].lower())

    for g in groups:
        g["teacher_name"] = tname.get(g["teacher_id"], "—")
        g["student_count"] = per_group.get(g["id"], 0)

    # Lidlar
    _abid = user.get("active_branch")
    try:
        leads = supabase.table("leads").select("status, created_at, branch_id").eq("center_id", cid).execute().data or []
    except Exception:
        leads = []
    leads = _bfilter(leads, _abid)
    leads_today = sum(1 for l in leads if (l.get("created_at") or "")[:10] == today)
    leads_active = sum(1 for l in leads if (l.get("status") or "new") not in ("enrolled", "lost"))

    # Shu oy foyda — faqat shu filial
    _bst = {s["id"] for s in students_all} if _abid else None
    _bte = {t["id"] for t in teachers} if _abid else None
    month_profit = (data.income_for_month(cid, now_ym, _bst)
                    - data.expenses_for_month(cid, now_ym, _abid)
                    - sum(data.payouts_for_month(cid, now_ym, _bte).values()))

    # Bugungi darslar — holat bo'yicha (hozir / keyin / o'tgan)
    wd = date.today().isoweekday()  # 1=Du..7=Yak
    gmap = {g["id"]: g for g in groups}
    cur_t = datetime.now().strftime("%H:%M")
    try:
        slots = supabase.table("schedule_slots").select("*").eq("center_id", cid).eq("weekday", wd).execute().data or []
    except Exception:
        slots = []
    today_lessons = []
    for s in slots:
        if s.get("group_id") not in gmap:   # boshqa filial darsi — ko'rsatmaymiz
            continue
        g = gmap.get(s.get("group_id"), {})
        st, en = s.get("start_time") or "", s.get("end_time") or ""
        if en and en <= cur_t:
            state, order = "past", 2
        elif st and st <= cur_t < (en or "99:99"):
            state, order = "now", 0
        else:
            state, order = "next", 1
        today_lessons.append({"name": g.get("name", "—"), "teacher": tname.get(g.get("teacher_id"), ""),
                              "time": f'{st}–{en}', "state": state, "order": order, "start": st})
    today_lessons.sort(key=lambda x: (x["order"], x["start"]))

    # Faol guruhlar reytingi (shu oy): avval baho, keyin davomat
    mstart = data.month_start()
    try:
        gmonth = supabase.table("grades").select("group_id, grade").eq("center_id", cid).gte("created_at", mstart).execute().data or []
    except Exception:
        gmonth = []
    try:
        amonth = supabase.table("attendance").select("group_id, status").eq("center_id", cid).gte("date", mstart).execute().data or []
    except Exception:
        amonth = []
    gr_by = {}
    for r in gmonth:
        if r.get("grade") is not None:
            gr_by.setdefault(r["group_id"], []).append(r["grade"])
    at_by = {}
    for a in amonth:
        t = at_by.setdefault(a["group_id"], [0, 0])
        t[1] += 1
        if a["status"] in ("present", "late"):
            t[0] += 1
    ranked = []
    for g in groups:
        gg = gr_by.get(g["id"], [])
        avg = round(sum(gg) / len(gg), 1) if gg else 0
        tot = at_by.get(g["id"], [0, 0])
        rate = round(tot[0] * 100 / tot[1]) if tot[1] else 0
        ranked.append({"name": g["name"], "teacher": g["teacher_name"],
                       "avg": avg, "rate": rate, "students": g["student_count"]})
    ranked.sort(key=lambda r: (r["avg"], r["rate"]), reverse=True)

    stats = {
        "students": len(students), "groups": len(groups), "teachers": len(teachers),
        "present": present, "absent": absent, "pending_payments": debtor_count,
        "total_debt": total_debt, "leads_today": leads_today, "leads_active": leads_active,
        "month_profit": month_profit,
    }
    try:
        _today = date.today().isoformat()
        news = supabase.table("news").select("*").order("created_at", desc=True).limit(8).execute().data or []
        news = [n for n in news if not n.get("expires_at") or str(n.get("expires_at"))[:10] >= _today][:2]
    except Exception:
        news = []

    return templates.TemplateResponse("owner_dashboard.html", {
        "request": request, "user": user, "active": "dashboard",
        "stats": stats, "attention": attention[:10], "groups": groups[:8], "news": news,
        "today_lessons": today_lessons, "ranked": ranked[:8], "month_label": _ym_label(now_ym),
        "birthdays": data.birthdays_this_month(cid)[:8],
    })


# ====================================================================
#  O'QUVCHILAR (fan/guruh filtri bilan, fanlari ko'rinadi)
# ====================================================================
@router.get("/students")
async def students_page(request: Request, user: dict = Depends(staff_required)):
    cid = user["center_id"]
    sel_group = request.query_params.get("group") or ""
    sel_status = request.query_params.get("status") or "active"
    q = (request.query_params.get("q") or "").strip().lower()

    groups = supabase.table("groups").select("id, name").eq("center_id", cid).order("name").execute().data or []
    gname = {g["id"]: g["name"] for g in groups}
    enr = data.center_enrollments(cid)
    subjects = {}
    for e in enr:
        subjects.setdefault(e["student_id"], []).append(gname.get(e["group_id"], "—"))

    students = supabase.table("students").select("*").eq("center_id", cid).order("created_at", desc=True).execute().data or []
    students = _bfilter(students, user.get("active_branch"))
    # holat (faol/ketgan)
    if sel_status == "active":
        students = [s for s in students if s.get("active", True) is not False]
    elif sel_status == "inactive":
        students = [s for s in students if s.get("active", True) is False]
    # fan filtri
    if sel_group:
        allowed = {e["student_id"] for e in enr if e["group_id"] == sel_group}
        students = [s for s in students if s["id"] in allowed]
    # qidiruv (ism yoki telefon)
    if q:
        students = [s for s in students if q in (s.get("full_name") or "").lower() or q in (s.get("parent_phone") or "").lower()]
    for s in students:
        s["subjects"] = subjects.get(s["id"], [])
        s["active"] = s.get("active", True) is not False

    return templates.TemplateResponse("owner_students.html", {
        "request": request, "user": user, "active": "students",
        "students": students, "groups": groups, "sel_group": sel_group,
        "sel_status": sel_status, "q": request.query_params.get("q") or "",
    })


@router.post("/students/add")
async def students_add(
    request: Request, user: dict = Depends(staff_required),
    full_name: str = Form(...), parent_phone: str = Form(""), group_id: str = Form(""),
    branch_id: str = Form(""),
):
    cid = user["center_id"]
    name = full_name.strip()
    phone = parent_phone.strip()
    bid = branch_id or user.get("active_branch") or None
    # dublikat: bir xil ism + telefon
    if phone:
        alls = supabase.table("students").select("full_name, parent_phone").eq("center_id", cid).execute().data or []
        if any((s.get("full_name") or "").strip().lower() == name.lower()
               and (s.get("parent_phone") or "").strip() == phone for s in alls):
            return RedirectResponse("/owner/students?dup=1", status_code=303)
    obj = {"center_id": cid, "full_name": name, "parent_phone": phone or None}
    if bid:
        obj["branch_id"] = bid
    try:
        res = supabase.table("students").insert(obj).execute().data
    except Exception:
        obj.pop("branch_id", None)
        res = supabase.table("students").insert(obj).execute().data
    sid = res[0]["id"] if res else None
    if sid and group_id:
        data.add_enrollment(cid, sid, group_id)
    return RedirectResponse("/owner/students", status_code=303)


# ====================================================================
#  GURUHLAR
# ====================================================================
@router.get("/groups")
async def groups_page(request: Request, user: dict = Depends(staff_required)):
    cid = user["center_id"]
    groups = supabase.table("groups").select("*").eq("center_id", cid).order("created_at", desc=True).execute().data or []
    groups = _bfilter(groups, user.get("active_branch"))
    teachers = supabase.table("teachers").select("id, full_name").eq("center_id", cid).execute().data or []
    tname = {t["id"]: t["full_name"] for t in teachers}

    enr = data.center_enrollments(cid)
    count = {}
    for e in enr:
        count[e["group_id"]] = count.get(e["group_id"], 0) + 1
    # navbatdagilar soni (guruh bo'yicha)
    wl = {}
    try:
        for w in (supabase.table("waitlist").select("group_id").eq("center_id", cid).execute().data or []):
            wl[w["group_id"]] = wl.get(w["group_id"], 0) + 1
    except Exception:
        wl = {}
    for g in groups:
        g["teacher_name"] = tname.get(g["teacher_id"], "—")
        g["student_count"] = count.get(g["id"], 0)
        g["waitlist_count"] = wl.get(g["id"], 0)
        cap = g.get("capacity")
        g["is_full"] = bool(cap) and g["student_count"] >= cap

    return templates.TemplateResponse("owner_groups.html", {
        "request": request, "user": user, "active": "groups",
        "groups": groups, "teachers": teachers,
    })


@router.post("/groups/add")
async def groups_add(
    request: Request, user: dict = Depends(owner_required),
    name: str = Form(...), subject: str = Form(""), teacher_id: str = Form(""),
    schedule_days: str = Form(""), schedule_time: str = Form(""), monthly_fee: str = Form(""),
    branch_id: str = Form(""),
):
    try:
        fee = float(str(monthly_fee).replace(" ", "").replace(",", "")) if monthly_fee.strip() else 0
    except ValueError:
        fee = 0
    bid = branch_id or user.get("active_branch") or None
    obj = {
        "center_id": user["center_id"], "name": name.strip(), "subject": subject.strip() or None,
        "teacher_id": teacher_id or None,
        "schedule_days": schedule_days.strip() or None, "schedule_time": schedule_time.strip() or None,
    }
    if bid:
        obj["branch_id"] = bid
    try:
        supabase.table("groups").insert(dict(obj, monthly_fee=fee)).execute()
    except Exception:
        obj.pop("branch_id", None)
        try:
            supabase.table("groups").insert(dict(obj, monthly_fee=fee)).execute()
        except Exception:
            supabase.table("groups").insert(obj).execute()
    return RedirectResponse("/owner/groups", status_code=303)


@router.get("/waitlist")
async def waitlist_page(request: Request, user: dict = Depends(staff_required)):
    cid = user["center_id"]
    try:
        rows = supabase.table("waitlist").select("*").eq("center_id", cid).order("created_at").execute().data or []
    except Exception:
        rows = []
    groups = {g["id"]: g for g in (_bfilter(supabase.table("groups").select("id, name, capacity, branch_id").eq("center_id", cid).execute().data or [], user.get("active_branch")))}
    enr = data.center_enrollments(cid)
    cnt = {}
    for e in enr:
        cnt[e["group_id"]] = cnt.get(e["group_id"], 0) + 1
    items = []
    for w in rows:
        if w.get("group_id") not in groups:   # boshqa filial navbati
            continue
        g = groups.get(w.get("group_id"), {})
        cap = g.get("capacity")
        items.append({
            "id": w["id"], "gid": w.get("group_id"), "full_name": w.get("full_name"),
            "phone": w.get("phone"), "note": w.get("note"),
            "group_name": g.get("name", "—"),
            "is_existing": bool(w.get("student_id")),
            "group_full": bool(cap) and cnt.get(w.get("group_id"), 0) >= cap,
            "free": (cap - cnt.get(w.get("group_id"), 0)) if cap else None,
        })
    return templates.TemplateResponse("owner_waitlist.html", {
        "request": request, "user": user, "active": "waitlist",
        "items": items,
    })


@router.get("/groups/{gid}")
async def group_detail(gid: str, request: Request, user: dict = Depends(staff_required)):
    cid = user["center_id"]
    grows = supabase.table("groups").select("*").eq("id", gid).eq("center_id", cid).limit(1).execute().data or []
    if not grows:
        return RedirectResponse("/owner/groups", status_code=303)
    group = grows[0]
    teachers = supabase.table("teachers").select("id, full_name").eq("center_id", cid).execute().data or []
    group["teacher_name"] = next((t["full_name"] for t in teachers if t["id"] == group["teacher_id"]), "—")

    in_group = data.enrolled_students(gid)
    in_ids = {s["id"] for s in in_group}
    all_students = supabase.table("students").select("id, full_name").eq("center_id", cid).order("full_name").execute().data or []
    others = [s for s in all_students if s["id"] not in in_ids]

    cap = group.get("capacity")
    enrolled_n = len(in_group)
    is_full = bool(cap) and enrolled_n >= cap
    try:
        waitlist = supabase.table("waitlist").select("*").eq("group_id", gid).order("created_at").execute().data or []
    except Exception:
        waitlist = []

    return templates.TemplateResponse("owner_group_detail.html", {
        "request": request, "user": user, "active": "groups",
        "group": group, "in_group": in_group, "others": others,
        "capacity": cap, "enrolled_n": enrolled_n, "is_full": is_full, "waitlist": waitlist,
    })


@router.post("/groups/{gid}/students/add")
async def group_add_student(gid: str, request: Request, user: dict = Depends(staff_required), student_id: str = Form(...)):
    cid = user["center_id"]
    grows = supabase.table("groups").select("capacity").eq("id", gid).eq("center_id", cid).limit(1).execute().data or []
    cap = grows[0].get("capacity") if grows else None
    if cap and len(data.enrolled_students(gid)) >= cap:
        return RedirectResponse(f"/owner/groups/{gid}?err=full", status_code=303)
    data.add_enrollment(cid, student_id, gid)
    return RedirectResponse(f"/owner/groups/{gid}", status_code=303)


@router.post("/groups/{gid}/capacity")
async def group_capacity(gid: str, request: Request, user: dict = Depends(staff_required), capacity: str = Form("")):
    try:
        cap = int(capacity) if capacity.strip() else None
    except ValueError:
        cap = None
    supabase.table("groups").update({"capacity": cap}).eq("id", gid).eq("center_id", user["center_id"]).execute()
    return RedirectResponse(f"/owner/groups/{gid}", status_code=303)


@router.post("/groups/{gid}/waitlist/add")
async def waitlist_add(gid: str, request: Request, user: dict = Depends(staff_required),
                       student_id: str = Form(""), full_name: str = Form(""),
                       phone: str = Form(""), note: str = Form("")):
    cid = user["center_id"]
    obj = {"center_id": cid, "group_id": gid, "note": note.strip() or None}
    if student_id.strip():
        srow = supabase.table("students").select("full_name, parent_phone").eq("id", student_id).eq("center_id", cid).limit(1).execute().data or []
        if not srow:
            return RedirectResponse(f"/owner/groups/{gid}", status_code=303)
        obj["full_name"] = srow[0]["full_name"]
        obj["phone"] = srow[0].get("parent_phone")
        obj["student_id"] = student_id
    else:
        if not full_name.strip():
            return RedirectResponse(f"/owner/groups/{gid}?err=noname", status_code=303)
        obj["full_name"] = full_name.strip()
        obj["phone"] = phone.strip() or None
    try:
        supabase.table("waitlist").insert(obj).execute()
    except Exception:
        supabase.table("waitlist").insert({"center_id": cid, "group_id": gid,
                                           "full_name": obj.get("full_name", "?"),
                                           "phone": obj.get("phone"), "note": obj.get("note")}).execute()
    return RedirectResponse(f"/owner/groups/{gid}", status_code=303)


@router.post("/groups/{gid}/waitlist/{wid}/enroll")
async def waitlist_enroll(gid: str, wid: str, request: Request, user: dict = Depends(staff_required)):
    """Navbatdagini guruhga o'tkazadi. Mavjud o'quvchi bo'lsa — to'g'ridan, yangi bo'lsa — o'quvchi yaratadi."""
    cid = user["center_id"]
    rows = supabase.table("waitlist").select("*").eq("id", wid).eq("center_id", cid).limit(1).execute().data or []
    if not rows:
        return RedirectResponse(f"/owner/groups/{gid}", status_code=303)
    w = rows[0]
    cap_rows = supabase.table("groups").select("capacity").eq("id", gid).eq("center_id", cid).limit(1).execute().data or []
    cap = cap_rows[0].get("capacity") if cap_rows else None
    if cap and len(data.enrolled_students(gid)) >= cap:
        return RedirectResponse(f"/owner/groups/{gid}?err=full", status_code=303)
    sid = w.get("student_id")
    try:
        if not sid:
            srow = supabase.table("students").insert({
                "center_id": cid, "full_name": w["full_name"], "parent_phone": w.get("phone"), "active": True,
            }).execute().data[0]
            sid = srow["id"]
            if w.get("lead_id"):
                try:
                    supabase.table("leads").update({"status": "enrolled", "student_id": sid,
                                                    "updated_at": datetime.now().isoformat()}).eq("id", w["lead_id"]).execute()
                except Exception:
                    pass
        data.add_enrollment(cid, sid, gid)
        supabase.table("waitlist").delete().eq("id", wid).execute()
    except Exception:
        pass
    return RedirectResponse(request.headers.get("referer") or f"/owner/groups/{gid}", status_code=303)


@router.post("/groups/{gid}/waitlist/{wid}/remove")
async def waitlist_remove(gid: str, wid: str, request: Request, user: dict = Depends(staff_required)):
    cid = user["center_id"]
    rows = supabase.table("waitlist").select("*").eq("id", wid).eq("center_id", cid).limit(1).execute().data or []
    if rows and rows[0].get("lead_id"):
        # eski bog'langan lid bo'lsa — "Yo'qotildi"ga o'tkazamiz (Yangida qolib ketmasin)
        try:
            supabase.table("leads").update({"status": "lost", "updated_at": datetime.now().isoformat()}).eq("id", rows[0]["lead_id"]).execute()
        except Exception:
            pass
    try:
        supabase.table("waitlist").delete().eq("id", wid).eq("center_id", cid).execute()
    except Exception:
        pass
    return RedirectResponse(request.headers.get("referer") or f"/owner/groups/{gid}", status_code=303)


@router.post("/groups/{gid}/students/remove")
async def group_remove_student(gid: str, request: Request, user: dict = Depends(staff_required), student_id: str = Form(...)):
    data.remove_enrollment(user["center_id"], student_id, gid)
    return RedirectResponse(f"/owner/groups/{gid}", status_code=303)


# ====================================================================
#  O'QITUVCHILAR (parol + foiz)
# ====================================================================
@router.get("/teachers")
async def teachers_page(request: Request, user: dict = Depends(staff_required)):
    cid = user["center_id"]
    teachers = supabase.table("teachers").select("*").eq("center_id", cid).order("created_at", desc=True).execute().data or []
    teachers = _bfilter(teachers, user.get("active_branch"))
    q = (request.query_params.get("q") or "").strip().lower()
    if q:
        teachers = [t for t in teachers if q in (t.get("full_name") or "").lower() or q in (t.get("subject") or "").lower()]
    for t in teachers:
        t["has_login"] = bool(t.get("password_hash"))
        t["commission_percent"] = t.get("commission_percent") or 0
    return templates.TemplateResponse("owner_teachers.html", {
        "request": request, "user": user, "active": "teachers", "teachers": teachers,
        "q": request.query_params.get("q") or "",
    })


@router.post("/teachers/add")
async def teachers_add(
    request: Request, user: dict = Depends(staff_required),
    full_name: str = Form(...), phone: str = Form(""), subject: str = Form(""),
    password: str = Form(""), commission_percent: str = Form(""),
    photo: UploadFile = File(None), branch_id: str = Form(""),
):
    obj = {
        "center_id": user["center_id"], "full_name": full_name.strip(),
        "phone": norm_phone(phone.strip()) or None, "subject": subject.strip() or None,
    }
    bid = branch_id or user.get("active_branch") or None
    if bid:
        obj["branch_id"] = bid
    if password.strip():
        from app.security import hash_password
        obj["password_hash"] = hash_password(password.strip())
    try:
        pct = float(str(commission_percent).replace(",", ".")) if commission_percent.strip() else 0
    except ValueError:
        pct = 0

    # Rasm yuklangan bo'lsa — saqlaymiz
    photo_url = None
    if photo is not None and getattr(photo, "filename", ""):
        ext = os.path.splitext(photo.filename)[1].lower()
        if ext in (".png", ".jpg", ".jpeg", ".webp"):
            try:
                import uuid as _uuid
                os.makedirs("app/static/uploads", exist_ok=True)
                fname = f"t_{_uuid.uuid4().hex}{ext}"
                content = await photo.read()
                if content:
                    with open(f"app/static/uploads/{fname}", "wb") as f:
                        f.write(content)
                    photo_url = f"/static/uploads/{fname}"
            except Exception:
                photo_url = None
    if photo_url:
        obj["photo_url"] = photo_url

    try:
        supabase.table("teachers").insert(dict(obj, commission_percent=pct)).execute()
    except Exception:
        # photo_url yoki branch_id yoki commission ustuni yo'q bo'lsa — graceful
        try:
            supabase.table("teachers").insert(dict(obj, commission_percent=pct)).execute()
        except Exception:
            obj.pop("photo_url", None)
            obj.pop("branch_id", None)
            supabase.table("teachers").insert(obj).execute()
    return RedirectResponse("/owner/teachers", status_code=303)


@router.post("/teachers/{tid}/password")
async def teacher_set_password(tid: str, request: Request, user: dict = Depends(staff_required), password: str = Form(...)):
    from app.security import hash_password
    supabase.table("teachers").update({"password_hash": hash_password(password.strip())}).eq("id", tid).eq("center_id", user["center_id"]).execute()
    return RedirectResponse("/owner/teachers", status_code=303)


@router.post("/teachers/{tid}/commission")
async def teacher_set_commission(tid: str, request: Request, user: dict = Depends(staff_required), commission_percent: str = Form("")):
    try:
        pct = float(str(commission_percent).replace(",", ".")) if commission_percent.strip() else 0
    except ValueError:
        pct = 0
    try:
        supabase.table("teachers").update({"commission_percent": pct}).eq("id", tid).eq("center_id", user["center_id"]).execute()
    except Exception:
        pass
    return RedirectResponse("/owner/teachers", status_code=303)


# ====================================================================
#  HISOBOTLAR
# ====================================================================
@router.get("/reports")
async def reports_page(request: Request, user: dict = Depends(staff_required)):
    cid = user["center_id"]
    _abid = user.get("active_branch")
    today = date.today()
    start = request.query_params.get("start") or today.replace(day=1).isoformat()
    end = request.query_params.get("end") or today.isoformat()

    groups = supabase.table("groups").select("id, name, teacher_id, branch_id").eq("center_id", cid).execute().data or []
    groups = _bfilter(groups, _abid)
    teachers = supabase.table("teachers").select("id, full_name, branch_id").eq("center_id", cid).execute().data or []
    teachers = _bfilter(teachers, _abid)
    students = supabase.table("students").select("id, full_name, parent_phone, active, branch_id").eq("center_id", cid).execute().data or []
    students = _bfilter(students, _abid)
    sname = {s["id"]: s["full_name"] for s in students}
    sphone = {s["id"]: s.get("parent_phone") for s in students}
    sactive = {s["id"]: (s.get("active", True) is not False) for s in students}
    tname = {t["id"]: t["full_name"] for t in teachers}
    _bst = set(sname.keys()) if _abid else None
    _bte = set(tname.keys()) if _abid else None

    # Kirim-chiqim (sana oralig'i) — shu filial
    def _sum(table, datecol, idcol=None, idset=None, bid=None):
        try:
            cols = "amount" + (f", {idcol}" if idcol else "") + (", branch_id" if bid is not None else "")
            rows = supabase.table(table).select(cols).eq("center_id", cid).gte(datecol, start).lte(datecol, end + "T23:59:59").execute().data or []
        except Exception:
            rows = []
        tot = 0.0
        for r in rows:
            if idset is not None and r.get(idcol) not in idset:
                continue
            if bid is not None and r.get("branch_id") != bid:
                continue
            tot += float(r.get("amount") or 0)
        return tot
    income = _sum("payments", "paid_at", "student_id", _bst)
    exp = _sum("expenses", "spent_at", bid=_abid)
    payouts = _sum("teacher_payouts", "paid_at", "teacher_id", _bte)
    profit = income - exp - payouts

    # Qarzdorlar
    debt_map = data.center_debtors(cid)
    debtors = sorted(
        [{"name": sname.get(sid, "—"), "phone": sphone.get(sid) or "—", "debt": d}
         for sid, d in debt_map.items() if sactive.get(sid, True) and (_bst is None or sid in _bst)],
        key=lambda x: -x["debt"])

    # Davomat (sana oralig'i) — har o'quvchi %
    att = data.attendance_by_student(cid, start, end)
    att_rows = []
    for sid, (p, t) in att.items():
        if not sactive.get(sid, True) or t == 0:
            continue
        if _bst is not None and sid not in _bst:
            continue
        att_rows.append({"name": sname.get(sid, "—"), "present": p, "total": t,
                         "rate": round(p * 100 / t)})
    att_rows.sort(key=lambda x: x["rate"])  # eng kam davomat birinchi

    # Guruhlar (umumiy)
    attendance = supabase.table("attendance").select("group_id, status").eq("center_id", cid).execute().data or []
    grades = supabase.table("grades").select("group_id, teacher_id, grade").eq("center_id", cid).execute().data or []
    lessons = supabase.table("lessons").select("group_id, teacher_id").eq("center_id", cid).execute().data or []
    enr = data.center_enrollments(cid)
    scount = {}
    for e in enr:
        scount[e["group_id"]] = scount.get(e["group_id"], 0) + 1
    group_rows = []
    for g in groups:
        gid = g["id"]
        ga = [a for a in attendance if a["group_id"] == gid]
        present = sum(1 for a in ga if a["status"] in ("present", "late"))
        total = len(ga)
        gg = [x["grade"] for x in grades if x["group_id"] == gid and x["grade"] is not None]
        group_rows.append({"name": g["name"], "teacher": tname.get(g["teacher_id"], "—"),
                           "rate": round(present * 100 / total) if total else 0,
                           "avg": round(sum(gg) / len(gg), 1) if gg else None,
                           "students": scount.get(gid, 0), "records": total})
    teacher_rows = []
    for t in teachers:
        tid = t["id"]
        teacher_rows.append({"name": t["full_name"],
                             "lessons": sum(1 for l in lessons if l["teacher_id"] == tid),
                             "grades": sum(1 for x in grades if x["teacher_id"] == tid)})

    return templates.TemplateResponse("owner_reports.html", {
        "request": request, "user": user, "active": "reports",
        "group_rows": group_rows, "teacher_rows": teacher_rows,
        "start": start, "end": end,
        "income": income, "exp": exp, "payouts": payouts, "profit": profit,
        "debtors": debtors[:200], "total_debt": sum(d["debt"] for d in debtors),
        "att_rows": att_rows[:200],
    })


def _csv_response(filename: str, header: list, rows: list):
    import io
    import csv as _csv
    buf = io.StringIO()
    buf.write("\ufeff")  # Excel UTF-8 BOM
    w = _csv.writer(buf)
    w.writerow(header)
    for r in rows:
        w.writerow(r)
    from fastapi.responses import Response
    return Response(content=buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/reports/export/debtors")
async def export_debtors(request: Request, user: dict = Depends(staff_required)):
    cid = user["center_id"]
    students = supabase.table("students").select("id, full_name, parent_phone, active").eq("center_id", cid).execute().data or []
    sname = {s["id"]: s["full_name"] for s in students}
    sphone = {s["id"]: s.get("parent_phone") for s in students}
    sactive = {s["id"]: (s.get("active", True) is not False) for s in students}
    debt_map = data.center_debtors(cid)
    rows = [[sname.get(sid, "—"), sphone.get(sid) or "", int(d)]
            for sid, d in sorted(debt_map.items(), key=lambda x: -x[1]) if sactive.get(sid, True)]
    return _csv_response("qarzdorlar.csv", ["O'quvchi", "Telefon", "Qarz (so'm)"], rows)


@router.get("/reports/export/payments")
async def export_payments(request: Request, user: dict = Depends(staff_required)):
    cid = user["center_id"]
    start = request.query_params.get("start") or date.today().replace(day=1).isoformat()
    end = request.query_params.get("end") or date.today().isoformat()
    students = supabase.table("students").select("id, full_name").eq("center_id", cid).execute().data or []
    groups = supabase.table("groups").select("id, name").eq("center_id", cid).execute().data or []
    sname = {s["id"]: s["full_name"] for s in students}
    gname = {g["id"]: g["name"] for g in groups}
    try:
        pays = (supabase.table("payments").select("*").eq("center_id", cid)
                .gte("paid_at", start).lte("paid_at", end + "T23:59:59")
                .order("paid_at", desc=True).execute().data) or []
    except Exception:
        pays = []
    rows = [[(p.get("paid_at") or "")[:10], sname.get(p.get("student_id"), "—"),
             gname.get(p.get("group_id"), "—"), int(float(p.get("amount") or 0)), p.get("method") or ""]
            for p in pays]
    return _csv_response("tolovlar.csv", ["Sana", "O'quvchi", "Fan", "Summa", "Usul"], rows)


@router.get("/reports/export/attendance")
async def export_attendance(request: Request, user: dict = Depends(staff_required)):
    cid = user["center_id"]
    start = request.query_params.get("start") or date.today().replace(day=1).isoformat()
    end = request.query_params.get("end") or date.today().isoformat()
    students = supabase.table("students").select("id, full_name, active").eq("center_id", cid).execute().data or []
    sname = {s["id"]: s["full_name"] for s in students}
    sactive = {s["id"]: (s.get("active", True) is not False) for s in students}
    att = data.attendance_by_student(cid, start, end)
    rows = []
    for sid, (p, t) in sorted(att.items(), key=lambda x: (x[1][0] / x[1][1]) if x[1][1] else 0):
        if not sactive.get(sid, True) or t == 0:
            continue
        rows.append([sname.get(sid, "—"), p, t, f"{round(p * 100 / t)}%"])
    return _csv_response("davomat.csv", ["O'quvchi", "Kelgan", "Jami dars", "Davomat %"], rows)


# ====================================================================
#  TO'LOVLAR — har o'quvchi×fan bo'yicha
# ====================================================================
UZ_MONTHS = ["", "Yanvar", "Fevral", "Mart", "Aprel", "May", "Iyun",
             "Iyul", "Avgust", "Sentyabr", "Oktyabr", "Noyabr", "Dekabr"]


def _ym_label(ym: str) -> str:
    try:
        y, m = ym.split("-")
        return f"{UZ_MONTHS[int(m)]} {y}"
    except Exception:
        return ym


# ====================================================================
#  TO'LOVLAR — oylik model (qaysi oy to'landi / qarz / oldindan)
# ====================================================================
@router.get("/payments")
async def payments_page(request: Request, user: dict = Depends(staff_required)):
    cid = user["center_id"]
    sel_group = request.query_params.get("group") or ""
    sel_status = request.query_params.get("status") or ""
    sel_month = request.query_params.get("month") or data.cur_ym()
    q = (request.query_params.get("q") or "").strip().lower()
    now_ym = data.cur_ym()

    students = supabase.table("students").select("*").eq("center_id", cid).execute().data or []
    students = _bfilter(students, user.get("active_branch"))
    sname = {s["id"]: s["full_name"] for s in students}
    active_ids = {s["id"] for s in students if s.get("active", True) is not False}
    groups = supabase.table("groups").select("id, name, branch_id").eq("center_id", cid).order("name").execute().data or []
    groups = _bfilter(groups, user.get("active_branch"))
    gname = {g["id"]: g["name"] for g in groups}
    _branch_sids = {s["id"] for s in students} if user.get("active_branch") else None
    pf = data.pair_fees(cid)
    paid_total = data.paid_total_by_pair(cid)
    starts = data.enrollment_starts(cid)
    coin_bal = coinmod.balances_for_center(cid)
    coin_value = int(coinmod.rules(cid).get("value", 100) or 100)

    enr = data.center_enrollments(cid)
    if sel_group:
        enr = [e for e in enr if e["group_id"] == sel_group]

    rows = []
    paid_cnt = owing_cnt = 0
    has_fee = False
    for e in enr:
        gid, sid = e["group_id"], e["student_id"]
        if sid not in active_ids:
            continue
        fee = pf.get((sid, gid), 0) or 0
        if fee > 0:
            has_fee = True
        start = starts.get((sid, gid)) or now_ym
        total_paid = paid_total.get((sid, gid), 0.0)
        alloc, st = data.alloc_for_month(start, now_ym, fee, total_paid, sel_month)
        summ = data.pair_summary(starts.get((sid, gid)) or now_ym, now_ym, fee, total_paid)
        if st == "full":
            paid_cnt += 1
        elif fee > 0 and st in ("partial", "unpaid"):
            owing_cnt += 1
        rows.append({"sid": sid, "gid": gid, "name": sname.get(sid, "—"),
                     "subject": gname.get(gid, "—"), "fee": fee, "alloc": alloc,
                     "month_left": max(0.0, fee - alloc) if fee > 0 else 0,
                     "status": st, "debt": summ["debt"], "ahead": summ["ahead"],
                     "coin": coin_bal.get(sid, 0), "coin_som": coin_bal.get(sid, 0) * coin_value})

    if sel_status == "paid":
        rows = [r for r in rows if r["status"] == "full"]
    elif sel_status == "owing":
        rows = [r for r in rows if r["status"] in ("partial", "unpaid")]
    if q:
        rows = [r for r in rows if q in r["name"].lower() or q in r["subject"].lower()]
    rows.sort(key=lambda r: (r["name"].lower(), r["subject"].lower()))

    months = [(ym, _ym_label(ym)) for ym in (data.add_months(now_ym, k) for k in range(-6, 7))]
    summary = {"paid": paid_cnt, "owing": owing_cnt,
               "collected": data.income_for_month(cid, sel_month, _branch_sids), "has_fee": has_fee}

    # 💳 To'lov turlari (TANLANGAN OY): Naqd va Naqddan tashqari
    pay_naqd = 0.0
    pay_noncash = 0.0
    _ms, _me = data.month_bounds(sel_month)
    try:
        prows = (supabase.table("payments").select("method, amount, student_id, paid_at")
                 .eq("center_id", cid).eq("status", "paid")
                 .gte("paid_at", _ms).lt("paid_at", _me).execute().data) or []
        for p in prows:
            if _branch_sids is not None and p.get("student_id") not in _branch_sids:
                continue
            m = (p.get("method") or "").strip()
            val = float(p.get("amount") or 0)
            if m == "naqd":
                pay_naqd += val
            elif m:
                pay_noncash += val
    except Exception:
        pass
    method_stats = [{"name": "Naqd", "sum": int(pay_naqd)},
                    {"name": "Naqddan tashqari", "sum": int(pay_noncash)}]

    return templates.TemplateResponse("owner_payments.html", {
        "request": request, "user": user, "active": "payments",
        "rows": rows, "groups": groups, "sel_group": sel_group, "sel_status": sel_status,
        "sel_month": sel_month, "month_label": _ym_label(sel_month), "months": months,
        "now_ym": now_ym, "is_current": sel_month == now_ym, "accounts": data.accounts(cid, branch_id=user.get("active_branch")),
        "q": request.query_params.get("q") or "", "summary": summary,
        "method_stats": method_stats,
        "err": request.query_params.get("err"),
    })


@router.post("/payments/pay")
async def payments_pay(
    request: Request, user: dict = Depends(staff_required),
    student_id: str = Form(...), group_id: str = Form(...), amount: str = Form(""),
    account_id: str = Form(""), method: str = Form(""), use_coins: str = Form(""),
    gfilter: str = Form(""), mfilter: str = Form(""),
):
    cid = user["center_id"]
    try:
        amt = float(str(amount).replace(" ", "").replace(",", "")) if amount.strip() else 0
    except ValueError:
        amt = 0
    err = ""
    # 🪙 coin sarflash (chegirma) — qiymati to'lov sifatida yoziladi (qarz kamayadi)
    try:
        uc = int(str(use_coins).strip() or 0)
    except ValueError:
        uc = 0
    if uc > 0:
        bal = coinmod.balance(student_id)
        uc = min(uc, bal)
        if uc > 0:
            cval = int(coinmod.rules(cid).get("value", 100) or 100)
            cbase = {"center_id": cid, "student_id": student_id, "amount": uc * cval,
                     "status": "paid", "paid_at": datetime.now().isoformat()}
            _insert_payment(cbase, group_id, "", "coin")
            coinmod.award(cid, student_id, -uc, "redeem", "To'lovda ishlatildi")
    if amt > 0:
        base = {"center_id": cid, "student_id": student_id, "amount": amt,
                "status": "paid", "paid_at": datetime.now().isoformat()}
        if not _insert_payment(base, group_id, account_id, method):
            err = "1"
        else:
            try:
                coinmod.award_rule(cid, student_id, "ontime", "To'lov qilindi")
            except Exception:
                pass
    params = []
    if gfilter:
        params.append(f"group={gfilter}")
    if mfilter:
        params.append(f"month={mfilter}")
    if err:
        params.append("err=1")
    dest = "/owner/payments" + ("?" + "&".join(params) if params else "")
    return RedirectResponse(dest, status_code=303)


# ====================================================================
#  O'QITUVCHILAR ULUSHI (maosh) — yig'ilgan puldan foiz
# ====================================================================
@router.get("/earnings")
async def earnings_page(request: Request, user: dict = Depends(staff_required)):
    cid = user["center_id"]
    teachers = supabase.table("teachers").select("*").eq("center_id", cid).execute().data or []
    teachers = _bfilter(teachers, user.get("active_branch"))
    groups = supabase.table("groups").select("id, teacher_id, branch_id").eq("center_id", cid).execute().data or []
    groups = _bfilter(groups, user.get("active_branch"))
    collected = data.collected_by_group(cid)
    payouts = data.payouts_this_month(cid)

    by_teacher = {}
    for g in groups:
        by_teacher[g["teacher_id"]] = by_teacher.get(g["teacher_id"], 0.0) + collected.get(g["id"], 0.0)

    rows = []
    attributed = total_earn = total_paid = total_remaining = 0.0
    for t in teachers:
        coll = by_teacher.get(t["id"], 0.0)
        pct = float(t.get("commission_percent") or 0)
        earn = coll * pct / 100
        paid = payouts.get(t["id"], 0.0)
        remaining = earn - paid
        attributed += coll
        total_earn += earn
        total_paid += paid
        total_remaining += remaining
        rows.append({"id": t["id"], "name": t["full_name"], "collected": coll,
                     "pct": pct, "earn": earn, "paid": paid, "remaining": remaining})
    rows.sort(key=lambda r: r["earn"], reverse=True)

    _abid = user.get("active_branch")
    if _abid:
        _bst = {s["id"] for s in supabase.table("students").select("id").eq("center_id", cid).eq("branch_id", _abid).execute().data or []}
        total_collected = data.income_for_month(cid, data.cur_ym(), _bst)
    else:
        total_collected = data.income_this_month(cid)
    unattributed = max(0.0, total_collected - attributed)

    return templates.TemplateResponse("owner_earnings.html", {
        "request": request, "user": user, "active": "earnings",
        "rows": rows, "total_collected": total_collected, "total_earn": total_earn,
        "total_paid": total_paid, "total_remaining": total_remaining,
        "unattributed": unattributed,
        "month": date.today().strftime("%Y-%m"),
    })


# ====================================================================
#  SOZLAMALAR — bo'limlarga bo'lingan hub
# ====================================================================
@router.get("/settings")
async def settings_hub(request: Request, user: dict = Depends(owner_required)):
    return templates.TemplateResponse("owner_settings.html", {
        "request": request, "user": user, "active": "settings",
    })


@router.get("/settings/general")
async def settings_general(request: Request, user: dict = Depends(owner_required)):
    c = _center_settings(user["center_id"])
    s = c.get("settings") or {}
    return templates.TemplateResponse("owner_settings_general.html", {
        "request": request, "user": user, "active": "settings",
        "center": c, "s": s, "settings": s, "saved": request.query_params.get("saved"),
    })


@router.post("/settings/general")
async def settings_general_save(
    request: Request, user: dict = Depends(owner_required),
    name: str = Form(...),
    phone: str = Form(""), phone2: str = Form(""), address: str = Form(""),
    telegram: str = Form(""), instagram: str = Form(""), website: str = Form(""),
    work_days: str = Form(""), work_start: str = Form(""), work_end: str = Form(""),
    logo: UploadFile = File(None),
):
    c = _center_settings(user["center_id"])
    s = dict(c.get("settings") or {})
    s["phone"] = phone.strip()
    s["phone2"] = phone2.strip()
    s["address"] = address.strip()
    s["telegram"] = telegram.strip()
    s["instagram"] = instagram.strip()
    s["website"] = website.strip()
    s["work_days"] = work_days.strip()
    s["work_start"] = work_start.strip()
    s["work_end"] = work_end.strip()
    # Eski "working_hours" matni — moslik uchun (boshqa joylar o'qisa buzilmasin)
    if work_start.strip() and work_end.strip():
        s["working_hours"] = f"{work_start.strip()} - {work_end.strip()}"
    # DIQQAT: centers.phone — egasining LOGIN telefoni. Uni bu yerda o'zgartirmaymiz!
    # Nom va sozlamalarni avval saqlaymiz (logo bo'lmasa ham ishlaydi)
    supabase.table("centers").update({"name": name.strip(), "settings": s}).eq("id", user["center_id"]).execute()

    # Logo yuklangan bo'lsa — alohida, xatoga chidamli saqlaymiz
    if logo is not None and getattr(logo, "filename", ""):
        ext = os.path.splitext(logo.filename)[1].lower()
        if ext in (".png", ".jpg", ".jpeg", ".webp", ".svg"):
            try:
                os.makedirs("app/static/uploads", exist_ok=True)
                fname = f"logo_{user['center_id']}{ext}"
                content = await logo.read()
                if content:
                    with open(f"app/static/uploads/{fname}", "wb") as f:
                        f.write(content)
                    import time as _t
                    url = f"/static/uploads/{fname}?v={int(_t.time())}"
                    supabase.table("centers").update({"logo_url": url}).eq("id", user["center_id"]).execute()
            except Exception:
                # logo_url ustuni hali yo'q bo'lsa — jim o'tamiz (migratsiya kerak)
                pass

    return RedirectResponse("/owner/settings/general?saved=1", status_code=303)


@router.get("/settings/messages")
async def settings_messages(request: Request, user: dict = Depends(owner_required)):
    c = _center_settings(user["center_id"])
    return templates.TemplateResponse("owner_settings_messages.html", {
        "request": request, "user": user, "active": "settings",
        "settings": c.get("settings") or {}, "saved": request.query_params.get("saved"),
    })


@router.post("/settings/messages")
async def settings_messages_save(request: Request, user: dict = Depends(owner_required), note_template: str = Form("")):
    c = _center_settings(user["center_id"])
    s = dict(c.get("settings") or {})
    s["note_template"] = note_template.strip()
    supabase.table("centers").update({"settings": s}).eq("id", user["center_id"]).execute()
    return RedirectResponse("/owner/settings/messages?saved=1", status_code=303)


@router.get("/settings/fees")
async def settings_fees(request: Request, user: dict = Depends(owner_required)):
    cid = user["center_id"]
    groups = supabase.table("groups").select("*").eq("center_id", cid).order("name").execute().data or []
    groups = _bfilter(groups, user.get("active_branch"))
    enr = data.center_enrollments(cid)
    cnt = {}
    for e in enr:
        cnt[e["group_id"]] = cnt.get(e["group_id"], 0) + 1
    for g in groups:
        g["count"] = cnt.get(g["id"], 0)
        g["expected"] = (float(g.get("monthly_fee") or 0)) * g["count"]
    return templates.TemplateResponse("owner_settings_fees.html", {
        "request": request, "user": user, "active": "settings",
        "groups": groups, "saved": request.query_params.get("saved"), "err": request.query_params.get("err"),
    })


@router.post("/settings/fees")
async def settings_fees_save(request: Request, user: dict = Depends(owner_required),
                             group_id: str = Form(...), monthly_fee: str = Form("")):
    try:
        fee = float(str(monthly_fee).replace(" ", "").replace(",", "")) if monthly_fee.strip() else 0
    except ValueError:
        fee = 0
    err = ""
    try:
        supabase.table("groups").update({"monthly_fee": fee}).eq("id", group_id).eq("center_id", user["center_id"]).execute()
    except Exception:
        err = "1"
    return RedirectResponse("/owner/settings/fees?" + ("err=1" if err else "saved=1"), status_code=303)


# ====================================================================
#  O'QITUVCHI — ALOHIDA PANEL (profil + oylik berildi/qoldi)
# ====================================================================
@router.get("/teachers/{tid}")
async def teacher_detail(tid: str, request: Request, user: dict = Depends(staff_required)):
    cid = user["center_id"]
    trows = supabase.table("teachers").select("*").eq("id", tid).eq("center_id", cid).limit(1).execute().data or []
    if not trows:
        return RedirectResponse("/owner/teachers", status_code=303)
    t = trows[0]
    t["has_login"] = bool(t.get("password_hash"))
    pct = float(t.get("commission_percent") or 0)

    groups = supabase.table("groups").select("*").eq("center_id", cid).eq("teacher_id", tid).execute().data or []
    enr = data.center_enrollments(cid)
    cnt = {}
    for e in enr:
        cnt[e["group_id"]] = cnt.get(e["group_id"], 0) + 1
    collected = data.collected_by_group(cid)
    g_rows = []
    coll_total = 0.0
    for g in groups:
        c = collected.get(g["id"], 0.0)
        coll_total += c
        g_rows.append({"name": g["name"], "subject": g.get("subject"),
                       "students": cnt.get(g["id"], 0), "collected": c})

    earned = coll_total * pct / 100
    paid = data.payouts_this_month(cid).get(tid, 0.0)
    remaining = earned - paid

    try:
        payouts = (supabase.table("teacher_payouts").select("*").eq("teacher_id", tid)
                   .eq("center_id", cid).order("paid_at", desc=True).limit(30).execute().data) or []
    except Exception:
        payouts = []

    return templates.TemplateResponse("owner_teacher_detail.html", {
        "request": request, "user": user, "active": "teachers",
        "t": t, "pct": pct, "groups": g_rows, "collected": coll_total,
        "earned": earned, "paid": paid, "remaining": remaining,
        "payouts": payouts, "month": date.today().strftime("%Y-%m"),
        "accounts": data.accounts(cid, branch_id=user.get("active_branch")),
        "saved": request.query_params.get("saved"), "err": request.query_params.get("err"),
    })


@router.post("/teachers/{tid}/payout")
async def teacher_payout(tid: str, request: Request, user: dict = Depends(staff_required),
                         amount: str = Form(...), note: str = Form(""),
                         account_id: str = Form(""), method: str = Form("")):
    try:
        amt = float(str(amount).replace(" ", "").replace(",", ""))
    except ValueError:
        amt = 0
    err = ""
    if amt > 0:
        short, bal = _insufficient(user["center_id"], account_id, amt)
        if short:
            return RedirectResponse(f"/owner/teachers/{tid}?err=nomoney&bal={int(bal)}&need={int(amt)}", status_code=303)
        base = {"center_id": user["center_id"], "teacher_id": tid, "amount": amt,
                "note": note.strip() or None, "paid_at": datetime.now().isoformat()}
        if not _insert_outflow("teacher_payouts", base, account_id, method):
            err = "1"
    return RedirectResponse(f"/owner/teachers/{tid}?" + ("err=1" if err else "saved=1"), status_code=303)


# ====================================================================
#  O'QUVCHI — ALOHIDA PANEL (fanlari + to'lovlari + tarix)
# ====================================================================
@router.get("/students/{sid}")
async def student_detail(sid: str, request: Request, user: dict = Depends(staff_required)):
    cid = user["center_id"]
    srows = supabase.table("students").select("*").eq("id", sid).eq("center_id", cid).limit(1).execute().data or []
    if not srows:
        return RedirectResponse("/owner/students", status_code=303)
    student = srows[0]

    all_groups = supabase.table("groups").select("*").eq("center_id", cid).order("name").execute().data or []
    gmap = {g["id"]: g for g in all_groups}
    try:
        enr = supabase.table("enrollments").select("group_id").eq("student_id", sid).eq("center_id", cid).execute().data or []
        my_gids = [e["group_id"] for e in enr]
    except Exception:
        my_gids = [student["group_id"]] if student.get("group_id") else []

    now_ym = data.cur_ym()
    starts = data.enrollment_starts(cid)
    paid_total = data.paid_total_by_pair(cid)
    discounts = data.enrollment_discounts(cid)
    gfees = data.group_fees(cid)
    rows = []
    total_fee = total_paid_all = total_debt = 0.0
    for gid in my_gids:
        g = gmap.get(gid)
        if not g:
            continue
        base = float(gfees.get(gid, 0) or 0)
        disc = float(discounts.get((sid, gid), 0) or 0)
        fee = max(0.0, base - disc)
        start = starts.get((sid, gid)) or now_ym
        tot = paid_total.get((sid, gid), 0.0)
        summ = data.pair_summary(start, now_ym, fee, tot)
        if fee > 0:
            months_alloc = int(tot // fee) + (1 if (tot % fee) > 0 else 0)
        else:
            months_alloc = 0
        last_paid = data.add_months(start, max(0, months_alloc - 1)) if months_alloc > 0 else start
        last = last_paid if last_paid > now_ym else now_ym
        cells = []
        for ym in data.months_range(start, last):
            alloc, st = data.alloc_for_month(start, now_ym, fee, tot, ym)
            cells.append({"label": _ym_label(ym), "alloc": alloc, "fee": fee,
                          "status": st, "current": ym == now_ym})
        total_fee += fee
        total_paid_all += tot
        total_debt += summ["debt"]
        rows.append({"gid": gid, "subject": g["name"], "fee": fee, "base": base, "discount": disc,
                     "total_paid": tot, "debt": summ["debt"], "ahead": summ["ahead"], "cells": cells})

    others = [g for g in all_groups if g["id"] not in set(my_gids)]
    try:
        history = (supabase.table("payments").select("*").eq("student_id", sid).eq("center_id", cid)
                   .order("paid_at", desc=True).limit(30).execute().data) or []
    except Exception:
        history = []
    for h in history:
        h["subject"] = gmap.get(h.get("group_id"), {}).get("name", "—")

    _tok = student.get("access_token")
    parent_link = f"{str(request.base_url).rstrip('/')}/p/{_tok}" if _tok else None
    return templates.TemplateResponse("owner_student_detail.html", {
        "request": request, "user": user, "active": "students",
        "student": student, "rows": rows, "others": others, "history": history,
        "is_active": student.get("active", True) is not False,
        "total_fee": total_fee, "total_paid": total_paid_all, "total_debt": total_debt,
        "now_label": _ym_label(now_ym), "accounts": data.accounts(cid, branch_id=user.get("active_branch")),
        "parent_link": parent_link,
        "coin_balance": coinmod.balance(sid), "coin_value": coinmod.rules(cid).get("value", 100),
    })


@router.post("/students/{sid}/enroll")
async def student_enroll(sid: str, request: Request, user: dict = Depends(staff_required), group_id: str = Form(...)):
    data.add_enrollment(user["center_id"], sid, group_id)
    return RedirectResponse(f"/owner/students/{sid}", status_code=303)


@router.post("/students/{sid}/unenroll")
async def student_unenroll(sid: str, request: Request, user: dict = Depends(staff_required), group_id: str = Form(...)):
    data.remove_enrollment(user["center_id"], sid, group_id)
    return RedirectResponse(f"/owner/students/{sid}", status_code=303)


@router.post("/students/{sid}/pay")
async def student_pay(sid: str, request: Request, user: dict = Depends(staff_required),
                      group_id: str = Form(...), amount: str = Form(""),
                      account_id: str = Form(""), method: str = Form(""), use_coins: str = Form("")):
    cid = user["center_id"]
    try:
        amt = float(str(amount).replace(" ", "").replace(",", "")) if amount.strip() else 0
    except ValueError:
        amt = 0
    # 🪙 Coin bilan to'lov (chegirma sifatida)
    try:
        coins = int(str(use_coins).strip() or 0)
    except ValueError:
        coins = 0
    if coins > 0:
        have = coinmod.balance(sid)
        coins = min(coins, have)
        if coins > 0:
            cval = int(coinmod.rules(cid).get("value", 100) or 100)
            coin_amt = coins * cval
            # coin qiymati to'lov sifatida yoziladi (qarz kamayadi), usuli = coin
            cbase = {"center_id": cid, "student_id": sid, "amount": coin_amt,
                     "status": "paid", "paid_at": datetime.now().isoformat()}
            _insert_payment(cbase, group_id, "", "coin")
            coinmod.award(cid, sid, -coins, "redeem", "To'lovda ishlatildi")
    if amt > 0:
        base = {"center_id": cid, "student_id": sid, "amount": amt,
                "status": "paid", "paid_at": datetime.now().isoformat()}
        _insert_payment(base, group_id, account_id, method)
    return RedirectResponse(f"/owner/students/{sid}", status_code=303)


# ====================================================================
#  CRM — LIDLAR (potensial o'quvchilar, sinov darsi)
# ====================================================================
LEAD_STATUSES = [("new", "Yangi"), ("contacted", "Aloqada"),
                 ("trial", "Sinov darsi"), ("enrolled", "O'quvchi bo'ldi"), ("lost", "Yo'qotildi")]


@router.get("/leads")
async def leads_page(request: Request, user: dict = Depends(staff_required)):
    cid = user["center_id"]
    q = (request.query_params.get("q") or "").strip().lower()
    try:
        leads = supabase.table("leads").select("*").eq("center_id", cid).order("created_at", desc=True).execute().data or []
    except Exception:
        leads = []
    leads = _bfilter(leads, user.get("active_branch"))
    groups = supabase.table("groups").select("id, name").eq("center_id", cid).order("name").execute().data or []
    gname = {g["id"]: g["name"] for g in groups}

    enrolled_all = sum(1 for l in leads if (l.get("status") or "new") == "enrolled")
    # "O'quvchi bo'ldi" va "Yo'qotildi" — o'sha kuni ko'rinadi, ertasiga board'dan ketadi.
    # (Navbatdan kelgan "Yangi" lidlar esa o'quvchi bo'lguncha doim turadi.)
    recent = date.today().isoformat()

    cols = {k: [] for k, _ in LEAD_STATUSES}
    for l in leads:
        st = l.get("status") or "new"
        if st in ("enrolled", "lost"):
            u = (l.get("updated_at") or l.get("created_at") or "")[:10]
            if u and u < recent:
                continue
        if q and not (q in (l.get("full_name") or "").lower() or q in (l.get("phone") or "").lower()):
            continue
        l["group_name"] = gname.get(l.get("group_id")) or l.get("subject") or ""
        cols.setdefault(st, []).append(l)
    counts = {k: len(v) for k, v in cols.items()}
    active_cnt = sum(1 for l in leads if (l.get("status") or "new") not in ("enrolled", "lost"))

    # VORONKA — barcha lidlar bo'yicha (board filtri emas)
    all_counts = {k: 0 for k, _ in LEAD_STATUSES}
    for l in leads:
        st = l.get("status") or "new"
        all_counts[st] = all_counts.get(st, 0) + 1
    total_all = len(leads)
    trial_n = all_counts.get("trial", 0)
    enrolled_n = all_counts.get("enrolled", 0)
    lost_n = all_counts.get("lost", 0)
    funnel = {
        "total": total_all,
        "trial": trial_n,
        "enrolled": enrolled_n,
        "lost": lost_n,
        "conv": round(enrolled_n * 100 / total_all) if total_all else 0,        # lid -> o'quvchi
        "trial_conv": round(enrolled_n * 100 / trial_n) if trial_n else 0,        # sinov -> o'quvchi
        "counts": all_counts,
    }

    return templates.TemplateResponse("owner_leads.html", {
        "request": request, "user": user, "active": "leads",
        "statuses": LEAD_STATUSES, "cols": cols, "counts": counts,
        "total": len(leads), "active_cnt": active_cnt, "enrolled": enrolled_all,
        "groups": groups, "q": request.query_params.get("q") or "", "funnel": funnel,
    })


@router.post("/leads/add")
async def leads_add(request: Request, user: dict = Depends(staff_required),
                    full_name: str = Form(...), phone: str = Form(""), group_id: str = Form(""),
                    source: str = Form(""), note: str = Form(""), trial_date: str = Form("")):
    cid = user["center_id"]
    name = full_name.strip()
    phone = phone.strip()
    if phone:
        alls = supabase.table("leads").select("full_name, phone").eq("center_id", cid).execute().data or []
        if any((x.get("full_name") or "").strip().lower() == name.lower()
               and (x.get("phone") or "").strip() == phone for x in alls):
            return RedirectResponse("/owner/leads?dup=1", status_code=303)
    subject = None
    if group_id:
        g = supabase.table("groups").select("name").eq("id", group_id).limit(1).execute().data or []
        subject = g[0]["name"] if g else None
    obj = {
        "center_id": cid, "full_name": name,
        "phone": phone or None, "subject": subject,
        "group_id": group_id or None,
        "source": source.strip() or None, "note": note.strip() or None, "status": "new",
    }
    if trial_date.strip():
        obj["trial_date"] = trial_date.strip()
        obj["status"] = "trial"
    _bid = user.get("active_branch")
    if _bid:
        obj["branch_id"] = _bid
    try:
        supabase.table("leads").insert(obj).execute()
    except Exception:
        obj.pop("branch_id", None)
        try:
            supabase.table("leads").insert(obj).execute()
        except Exception:
            obj.pop("group_id", None)
            try:
                supabase.table("leads").insert(obj).execute()
            except Exception:
                pass
    return RedirectResponse("/owner/leads", status_code=303)


@router.post("/leads/{lid}/status")
async def leads_status(lid: str, request: Request, user: dict = Depends(staff_required), status: str = Form(...)):
    try:
        supabase.table("leads").update({"status": status, "updated_at": datetime.now().isoformat()}).eq("id", lid).eq("center_id", user["center_id"]).execute()
    except Exception:
        pass
    return RedirectResponse("/owner/leads", status_code=303)


@router.post("/leads/{lid}/convert")
async def leads_convert(lid: str, request: Request, user: dict = Depends(staff_required)):
    cid = user["center_id"]
    rows = supabase.table("leads").select("*").eq("id", lid).eq("center_id", cid).limit(1).execute().data or []
    if rows:
        l = rows[0]
        res = supabase.table("students").insert({
            "center_id": cid, "full_name": l["full_name"], "parent_phone": l.get("phone"),
        }).execute().data
        sid = res[0]["id"] if res else None
        # tanlangan fanga (guruhga) avtomatik yozamiz
        if sid and l.get("group_id"):
            data.add_enrollment(cid, sid, l["group_id"])
        supabase.table("leads").update({"status": "enrolled", "student_id": sid, "updated_at": datetime.now().isoformat()}).eq("id", lid).execute()
    return RedirectResponse("/owner/leads", status_code=303)


@router.post("/leads/{lid}/delete")
async def leads_delete(lid: str, request: Request, user: dict = Depends(staff_required)):
    try:
        supabase.table("leads").delete().eq("id", lid).eq("center_id", user["center_id"]).execute()
    except Exception:
        pass
    return RedirectResponse("/owner/leads", status_code=303)


# ====================================================================
#  DARS JADVALI + XONALAR
# ====================================================================
WEEKDAYS = [(1, "Dushanba"), (2, "Seshanba"), (3, "Chorshanba"),
            (4, "Payshanba"), (5, "Juma"), (6, "Shanba"), (7, "Yakshanba")]
_DAY_START, _DAY_END = 8 * 60, 22 * 60
_SPAN = _DAY_END - _DAY_START
_PALETTE = [("#e0f0ee", "#0b5c55"), ("#fbeede", "#9a6b14"), ("#e7eefb", "#2f4d8a"),
            ("#f3e8f5", "#7a3d86"), ("#e6f3eb", "#1f7a52"), ("#fde9e4", "#a23c28"),
            ("#e9eef0", "#3a5560"), ("#f0eede", "#6b6320")]


def _to_min(t):
    try:
        h, m = str(t).split(":")[:2]
        return int(h) * 60 + int(m)
    except Exception:
        return None


def _color_for(gid):
    return _PALETTE[sum(ord(c) for c in str(gid)) % len(_PALETTE)]


@router.get("/schedule")
async def schedule_page(request: Request, user: dict = Depends(staff_required)):
    cid = user["center_id"]
    _abid = user.get("active_branch")
    rooms = supabase.table("rooms").select("*").eq("center_id", cid).order("name").execute().data or []
    rooms = _bfilter(rooms, _abid)
    groups_full = supabase.table("groups").select("id, name, subject, teacher_id, branch_id").eq("center_id", cid).order("name").execute().data or []
    groups = _bfilter(groups_full, _abid)
    teachers = supabase.table("teachers").select("id, full_name").eq("center_id", cid).execute().data or []
    tname = {t["id"]: t["full_name"] for t in teachers}
    gmap = {g["id"]: g for g in groups}
    rmap = {r["id"]: r["name"] for r in rooms}
    try:
        slots = supabase.table("schedule_slots").select("*").eq("center_id", cid).execute().data or []
    except Exception:
        slots = []
    if _abid:
        # faqat shu filial guruhlari/xonalariga tegishli slotlar
        _gids = {g["id"] for g in groups}
        _rids = {r["id"] for r in rooms}
        slots = [s for s in slots if (s.get("group_id") in _gids) or (s.get("room_id") in _rids)]

    # Har guruhda nechta o'quvchi (enrollments)
    try:
        enr = supabase.table("enrollments").select("group_id").eq("center_id", cid).execute().data or []
    except Exception:
        enr = []
    gcount = {}
    for e in enr:
        gid = e.get("group_id")
        if gid:
            gcount[gid] = gcount.get(gid, 0) + 1

    # Bugungi davomat (kelgan / jami belgilangan) — har guruh bo'yicha
    now = datetime.now()
    cur_wd = now.isoweekday()
    cur_min = now.hour * 60 + now.minute
    today_iso = date.today().isoformat()
    try:
        att = supabase.table("attendance").select("group_id, status").eq("center_id", cid).eq("date", today_iso).execute().data or []
    except Exception:
        att = []
    g_present, g_marked = {}, {}
    for a in att:
        gid = a.get("group_id")
        if not gid:
            continue
        g_marked[gid] = g_marked.get(gid, 0) + 1
        if a.get("status") in ("present", "late"):
            g_present[gid] = g_present.get(gid, 0) + 1

    days = []
    for wd, label in WEEKDAYS:
        blocks = []
        for s in slots:
            if int(s.get("weekday") or 0) != wd:
                continue
            st, en = _to_min(s.get("start_time")), _to_min(s.get("end_time"))
            if st is None or en is None or en <= st:
                continue
            gid = s["group_id"]
            g = gmap.get(gid, {})
            bg, fg = _color_for(gid)
            is_today = (wd == cur_wd)
            blocks.append({
                "id": s["id"], "name": g.get("name", "—"),
                "room": rmap.get(s.get("room_id"), ""), "teacher": tname.get(g.get("teacher_id"), ""),
                "time": f'{s.get("start_time")}–{s.get("end_time")}',
                "top": round((st - _DAY_START) / _SPAN * 100, 2),
                "height": round(max(7, (en - st) / _SPAN * 100), 2),
                "bg": bg, "fg": fg,
                "students": gcount.get(gid, 0),
                "att_today": is_today,
                "att_present": g_present.get(gid, 0) if is_today else None,
                "att_marked": g_marked.get(gid, 0) if is_today else None,
            })
        blocks.sort(key=lambda b: b["top"])
        _short = {1: "Du", 2: "Se", 3: "Cho", 4: "Pay", 5: "Ju", 6: "Sha", 7: "Yak"}
        days.append({"label": label, "short": _short.get(wd, label[:2]), "wd": wd, "blocks": blocks})

    hours = [{"label": f"{h:02d}:00", "top": round((h * 60 - _DAY_START) / _SPAN * 100, 2)} for h in range(8, 23)]

    # Xonalar bandligi — hozirgi vaqtga qarab
    busy = {}
    for s in slots:
        if int(s.get("weekday") or 0) != cur_wd or not s.get("room_id"):
            continue
        st, en = _to_min(s.get("start_time")), _to_min(s.get("end_time"))
        if st is None or en is None:
            continue
        if st <= cur_min < en:
            g = gmap.get(s["group_id"], {})
            busy[s["room_id"]] = {"group": g.get("name", "—"),
                                  "time": f'{s.get("start_time")}–{s.get("end_time")}',
                                  "teacher": tname.get(g.get("teacher_id"), "")}
    room_status = [{"name": r["name"], "busy": r["id"] in busy, "info": busy.get(r["id"])} for r in rooms]
    free_cnt = sum(1 for r in room_status if not r["busy"])

    # Bugungi kun filtri (on/off)
    today_only = request.query_params.get("view") == "today"
    _short = {1: "Du", 2: "Se", 3: "Cho", 4: "Pay", 5: "Ju", 6: "Sha", 7: "Yak"}
    _full = {1: "Dushanba", 2: "Seshanba", 3: "Chorshanba", 4: "Payshanba", 5: "Juma", 6: "Shanba", 7: "Yakshanba"}
    shown_days = [d for d in days if d["wd"] == cur_wd] if today_only else days

    # 📅 Bugun bayrammi?
    today_holiday = _holiday_dates(cid).get(today_iso)

    return templates.TemplateResponse("owner_schedule.html", {
        "request": request, "user": user, "active": "schedule",
        "rooms": rooms, "groups": groups, "days": shown_days, "hours": hours,
        "weekdays": WEEKDAYS, "err": request.query_params.get("err"),
        "has_slots": bool(slots), "room_status": room_status, "free_cnt": free_cnt,
        "now_label": now.strftime("%H:%M"),
        "today_only": today_only, "today_label": _full.get(cur_wd, ""),
        "today_holiday": today_holiday,
    })


@router.post("/schedule/add")
async def schedule_add(request: Request, user: dict = Depends(staff_required),
                       group_id: str = Form(...), room_id: str = Form(""),
                       start_time: str = Form(...), end_time: str = Form(...)):
    cid = user["center_id"]
    form = await request.form()
    raw_days = form.getlist("weekdays") or ([form.get("weekday")] if form.get("weekday") else [])
    wds = []
    for x in raw_days:
        try:
            v = int(x)
            if 1 <= v <= 7:
                wds.append(v)
        except (ValueError, TypeError):
            continue
    st, en = _to_min(start_time), _to_min(end_time)
    if st is None or en is None or en <= st:
        return RedirectResponse("/owner/schedule?err=time", status_code=303)
    if not wds:
        return RedirectResponse("/owner/schedule?err=noday", status_code=303)

    g = supabase.table("groups").select("teacher_id").eq("id", group_id).limit(1).execute().data or []
    new_teacher = g[0]["teacher_id"] if g else None
    try:
        allslots = supabase.table("schedule_slots").select("*").eq("center_id", cid).execute().data or []
    except Exception:
        allslots = []
    # o'qituvchi id'larini oldindan yig'amiz (to'qnashuv tekshiruvi uchun)
    tcache = {}
    short = {1: "Du", 2: "Se", 3: "Cho", 4: "Pay", 5: "Ju", 6: "Sha", 7: "Yak"}

    added = 0
    room_conf, teacher_conf = [], []
    for wd in sorted(set(wds)):
        conflict_room = conflict_teacher = False
        for e in allslots:
            if int(e.get("weekday") or 0) != wd:
                continue
            es, ee = _to_min(e.get("start_time")), _to_min(e.get("end_time"))
            if es is None or ee is None or not (st < ee and es < en):
                continue
            if room_id and e.get("room_id") == room_id:
                conflict_room = True
            if new_teacher:
                gid = e.get("group_id")
                if gid not in tcache:
                    eg = supabase.table("groups").select("teacher_id").eq("id", gid).limit(1).execute().data or []
                    tcache[gid] = eg[0].get("teacher_id") if eg else None
                if tcache[gid] == new_teacher:
                    conflict_teacher = True
        if conflict_room:
            room_conf.append(short.get(wd, str(wd)))
            continue
        if conflict_teacher:
            teacher_conf.append(short.get(wd, str(wd)))
            continue
        try:
            supabase.table("schedule_slots").insert({
                "center_id": cid, "group_id": group_id, "room_id": room_id or None,
                "weekday": wd, "start_time": start_time, "end_time": end_time,
            }).execute()
            added += 1
            allslots.append({"weekday": wd, "start_time": start_time, "end_time": end_time,
                             "room_id": room_id or None, "group_id": group_id})
        except Exception:
            pass

    params = [f"added={added}"]
    if room_conf:
        params.append("roomconf=" + ".".join(room_conf))
    if teacher_conf:
        params.append("teachconf=" + ".".join(teacher_conf))
    return RedirectResponse("/owner/schedule?" + "&".join(params), status_code=303)


@router.post("/schedule/{sid}/delete")
async def schedule_delete(sid: str, request: Request, user: dict = Depends(staff_required)):
    try:
        supabase.table("schedule_slots").delete().eq("id", sid).eq("center_id", user["center_id"]).execute()
    except Exception:
        pass
    return RedirectResponse("/owner/schedule", status_code=303)


@router.post("/schedule/generate")
async def schedule_generate(request: Request, user: dict = Depends(staff_required)):
    """Namuna jadval: 3 dars/kun, Du–Sha. Toq kunlar (Du/Cho/Ju) bir xil vaqtda."""
    cid = user["center_id"]
    groups = supabase.table("groups").select("id, teacher_id").eq("center_id", cid).execute().data or []
    if not groups:
        return RedirectResponse("/owner/schedule?err=nogroups", status_code=303)
    rooms = supabase.table("rooms").select("id").eq("center_id", cid).order("name").execute().data or []
    for i in range(max(0, 3 - len(rooms))):
        try:
            r = supabase.table("rooms").insert({"center_id": cid, "name": f"{len(rooms) + 1}-xona"}).execute().data[0]
            rooms.append(r)
        except Exception:
            pass
    room_ids = [r["id"] for r in rooms] or [None]
    try:
        supabase.table("schedule_slots").delete().eq("center_id", cid).execute()
    except Exception:
        pass
    times_odd = [("09:00", "10:30"), ("11:00", "12:30"), ("14:00", "15:30")]
    times_even = [("10:00", "11:30"), ("13:00", "14:30"), ("16:00", "17:30")]
    gi = 0
    created = 0
    for wd in range(1, 7):  # 1=Du .. 6=Sha
        times = times_odd if wd % 2 == 1 else times_even
        for i, (st, en) in enumerate(times):
            g = groups[gi % len(groups)]
            gi += 1
            obj = {"center_id": cid, "group_id": g["id"], "weekday": wd, "start_time": st, "end_time": en}
            rid = room_ids[i % len(room_ids)]
            if rid:
                obj["room_id"] = rid
            try:
                supabase.table("schedule_slots").insert(obj).execute()
                created += 1
            except Exception:
                pass
    return RedirectResponse(f"/owner/schedule?gen={created}", status_code=303)


@router.post("/rooms/add")
async def rooms_add(request: Request, user: dict = Depends(staff_required),
                    name: str = Form(...), capacity: str = Form("")):
    try:
        cap = int(capacity) if capacity.strip() else None
    except ValueError:
        cap = None
    obj = {"center_id": user["center_id"], "name": name.strip(), "capacity": cap}
    bid = user.get("active_branch")
    if bid:
        obj["branch_id"] = bid
    try:
        supabase.table("rooms").insert(obj).execute()
    except Exception:
        obj.pop("branch_id", None)
        try:
            supabase.table("rooms").insert(obj).execute()
        except Exception:
            pass
    return RedirectResponse("/owner/schedule", status_code=303)


@router.post("/rooms/{rid}/delete")
async def rooms_delete(rid: str, request: Request, user: dict = Depends(staff_required)):
    try:
        supabase.table("rooms").delete().eq("id", rid).eq("center_id", user["center_id"]).execute()
    except Exception:
        pass
    return RedirectResponse("/owner/schedule", status_code=303)


# ====================================================================
#  KASSA — KIRIM / CHIQIM -> SOF FOYDA
# ====================================================================
EXPENSE_CATS = ["Ijara", "Kommunal", "Reklama", "Jihoz", "Soliq", "Boshqa"]


@router.get("/cashbox")
async def cashbox_page(request: Request, user: dict = Depends(staff_required)):
    cid = user["center_id"]
    sel_month = request.query_params.get("month") or data.cur_ym()
    _abid = user.get("active_branch")
    _bst, _bgr, _bte = data.branch_members(cid, _abid)
    income = data.income_for_month(cid, sel_month, _bst)
    exp_sum = data.expenses_for_month(cid, sel_month, _abid)
    payouts = sum(data.payouts_for_month(cid, sel_month, _bte).values())
    total_out = exp_sum + payouts
    profit = income - total_out

    s, e = data.month_bounds(sel_month)
    try:
        expenses = (supabase.table("expenses").select("*").eq("center_id", cid)
                    .gte("spent_at", s).lt("spent_at", e).order("spent_at", desc=True).execute().data) or []
    except Exception:
        expenses = []
    expenses = _bfilter(expenses, _abid)

    cat = {}
    for ex in expenses:
        k = ex.get("category") or "Boshqa"
        cat[k] = cat.get(k, 0.0) + float(ex["amount"] or 0)
    if payouts > 0:
        cat["O'qituvchi oyligi"] = cat.get("O'qituvchi oyligi", 0.0) + payouts
    cats = sorted(cat.items(), key=lambda x: -x[1])
    cat_max = cats[0][1] if cats else 0

    accs = data.accounts(cid, only_active=False, branch_id=_abid)
    bals = data.account_balances(cid, branch_id=_abid)
    acc_rows = [dict(a, balance=bals.get(a["id"], 0.0)) for a in accs]
    total_balance = sum(b for b in bals.values())

    return templates.TemplateResponse("owner_cashbox.html", {
        "request": request, "user": user, "active": "cashbox",
        "income": income, "expenses_sum": exp_sum, "payouts": payouts,
        "total_out": total_out, "profit": profit, "expenses": expenses,
        "cats": cats, "cat_max": cat_max, "categories": EXPENSE_CATS,
        "accounts": acc_rows, "total_balance": total_balance, "acc_active": [a for a in acc_rows if a.get("is_active", True) is not False],
        "sel_month": sel_month, "month_label": _ym_label(sel_month),
        "prev_month": data.add_months(sel_month, -1), "next_month": data.add_months(sel_month, 1),
        "saved": request.query_params.get("saved"), "err": request.query_params.get("err"),
    })


@router.post("/cashbox/expense/add")
async def cashbox_expense_add(request: Request, user: dict = Depends(staff_required),
                              category: str = Form(""), amount: str = Form(...),
                              note: str = Form(""), spent_at: str = Form(""), back_month: str = Form(""),
                              account_id: str = Form(""), method: str = Form("")):
    try:
        amt = float(str(amount).replace(" ", "").replace(",", ""))
    except ValueError:
        amt = 0
    err = ""
    if amt > 0:
        short, bal = _insufficient(user["center_id"], account_id, amt)
        if short:
            qs = f"?err=nomoney&bal={int(bal)}&need={int(amt)}" + (f"&month={back_month}" if back_month else "")
            return RedirectResponse("/owner/cashbox" + qs, status_code=303)
        obj = {"center_id": user["center_id"], "category": category.strip() or "Boshqa",
               "amount": amt, "note": note.strip() or None}
        if user.get("active_branch"):
            obj["branch_id"] = user["active_branch"]
        if spent_at.strip():
            obj["spent_at"] = spent_at.strip()
        if not _insert_outflow("expenses", obj, account_id, method):
            err = "1"
    qs = "?saved=1" + (f"&month={back_month}" if back_month else "")
    if err:
        qs = "?err=1" + (f"&month={back_month}" if back_month else "")
    return RedirectResponse("/owner/cashbox" + qs, status_code=303)


@router.post("/cashbox/account/add")
async def cashbox_account_add(request: Request, user: dict = Depends(staff_required),
                              name: str = Form(...), kind: str = Form("cash"),
                              card_number: str = Form(""), opening_balance: str = Form("")):
    try:
        ob = float(str(opening_balance).replace(" ", "").replace(",", "")) if opening_balance.strip() else 0
    except ValueError:
        ob = 0
    try:
        obj = {
            "center_id": user["center_id"], "name": name.strip() or "Hisob",
            "kind": kind.strip() or "cash", "card_number": card_number.strip() or None,
            "opening_balance": ob,
        }
        if user.get("active_branch"):
            obj["branch_id"] = user["active_branch"]
        try:
            supabase.table("accounts").insert(obj).execute()
        except Exception:
            obj.pop("branch_id", None)
            supabase.table("accounts").insert(obj).execute()
    except Exception:
        pass
    return RedirectResponse("/owner/cashbox?saved=1", status_code=303)


@router.post("/cashbox/account/{aid}/delete")
async def cashbox_account_delete(aid: str, request: Request, user: dict = Depends(staff_required)):
    """Hisobni o'chirmaymiz (tarix uchun) — nofaol qilamiz."""
    try:
        supabase.table("accounts").update({"is_active": False}).eq("id", aid).eq("center_id", user["center_id"]).execute()
    except Exception:
        pass
    return RedirectResponse("/owner/cashbox", status_code=303)


@router.post("/cashbox/expense/{eid}/delete")
async def cashbox_expense_delete(eid: str, request: Request, user: dict = Depends(staff_required)):
    try:
        supabase.table("expenses").delete().eq("id", eid).eq("center_id", user["center_id"]).execute()
    except Exception:
        pass
    return RedirectResponse("/owner/cashbox", status_code=303)


@router.post("/students/{sid}/archive")
async def student_archive(sid: str, request: Request, user: dict = Depends(staff_required)):
    cid = user["center_id"]
    try:
        supabase.table("students").update({"active": False}).eq("id", sid).eq("center_id", cid).execute()
    except Exception:
        pass
    # ketgan o'quvchini fanlardan chiqaramiz (qarz hisoblanmasin) — tarix saqlanadi
    try:
        supabase.table("enrollments").delete().eq("student_id", sid).eq("center_id", cid).execute()
    except Exception:
        pass
    return RedirectResponse(f"/owner/students/{sid}", status_code=303)


@router.post("/students/{sid}/activate")
async def student_activate(sid: str, request: Request, user: dict = Depends(staff_required)):
    try:
        supabase.table("students").update({"active": True}).eq("id", sid).eq("center_id", user["center_id"]).execute()
    except Exception:
        pass
    return RedirectResponse(f"/owner/students/{sid}", status_code=303)


@router.post("/students/{sid}/delete")
async def student_delete(sid: str, request: Request, user: dict = Depends(owner_required)):
    try:
        supabase.table("students").delete().eq("id", sid).eq("center_id", user["center_id"]).execute()
    except Exception:
        pass
    return RedirectResponse("/owner/students", status_code=303)


# ====================================================================
#  O'QITUVCHI NAZORATI — o'zgartirishlar tarixi (owner ko'radi)
# ====================================================================
@router.get("/monitoring")
async def monitoring_page(request: Request, user: dict = Depends(staff_required)):
    cid = user["center_id"]
    table_ok = True
    try:
        edits = (supabase.table("record_edits").select("*").eq("center_id", cid)
                 .order("created_at", desc=True).limit(100).execute().data) or []
    except Exception:
        edits = []
        table_ok = False
    _abid = user.get("active_branch")
    _allt = supabase.table("teachers").select("id, full_name, branch_id").eq("center_id", cid).execute().data or []
    _bteach = _bfilter(_allt, _abid)
    teachers = {t["id"]: t["full_name"] for t in _bteach}
    if _abid:
        _bset = set(teachers.keys())
        edits = [e for e in edits if e.get("teacher_id") in _bset]
    students = {s["id"]: s["full_name"] for s in supabase.table("students").select("id, full_name").eq("center_id", cid).execute().data or []}
    groups = {g["id"]: g["name"] for g in supabase.table("groups").select("id, name").eq("center_id", cid).execute().data or []}

    def _disp(kind, v):
        if kind == "attendance":
            return {"present": "Keldi", "absent": "Kelmadi", "late": "Kechikdi"}.get(v, v)
        return v

    for e in edits:
        e["teacher"] = teachers.get(e.get("teacher_id"), "—")
        e["student"] = students.get(e.get("student_id"), "—")
        e["group"] = groups.get(e.get("group_id"), "—")
        e["kind_label"] = "Davomat" if e.get("kind") == "attendance" else "Baho"
        e["old_disp"] = _disp(e.get("kind"), e.get("old_value"))
        e["new_disp"] = _disp(e.get("kind"), e.get("new_value"))

    return templates.TemplateResponse("owner_monitoring.html", {
        "request": request, "user": user, "active": "monitoring", "edits": edits,
        "table_ok": table_ok,
    })


# ====================================================================
#  OBUNA — markaz egasi o'z obunasini ko'radi
# ====================================================================
@router.get("/settings/subscription")
async def settings_subscription(request: Request, user: dict = Depends(owner_required)):
    cid = user["center_id"]
    rows = supabase.table("centers").select("*").eq("id", cid).limit(1).execute().data or [{}]
    c = rows[0]
    branch_rows = data.branch_billing_rows(cid, c)
    for b in branch_rows:
        b["accounts"] = data.accounts(cid, branch_id=b["id"])
    su = c.get("subscription_until")
    days = None
    if su:
        try:
            days = (date.fromisoformat(su[:10]) - date.today()).days
        except Exception:
            days = None
    try:
        history = (supabase.table("center_payments").select("*").eq("center_id", cid)
                   .order("paid_at", desc=True).limit(40).execute().data) or []
    except Exception:
        history = []
    total = sum(float(h["amount"] or 0) for h in history)
    # filialsiz markaz uchun oylik formula bo'yicha
    center_fee = data.center_monthly_fee(cid, c) if not branch_rows else 0
    return templates.TemplateResponse("owner_settings_subscription.html", {
        "request": request, "user": user, "active": "settings",
        "center": c, "days": days, "history": history, "total": total,
        "monthly_fee": center_fee, "accounts": data.accounts(cid),
        "branch_rows": branch_rows,
        "saved": request.query_params.get("saved"), "err": request.query_params.get("err"),
    })


def _add_months_date(d: date, n: int) -> date:
    idx = d.year * 12 + (d.month - 1) + n
    y, m = idx // 12, idx % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


@router.post("/settings/subscription/pay")
async def settings_subscription_pay(request: Request, user: dict = Depends(owner_required),
                                    months: str = Form("1"), account_id: str = Form(""),
                                    method: str = Form(""), branch_id: str = Form("")):
    """Markaz egasi obunani o'zi to'laydi. branch_id berilsa — o'sha filial obunasi."""
    cid = user["center_id"]
    rows = supabase.table("centers").select("*").eq("id", cid).limit(1).execute().data or []
    if not rows:
        return RedirectResponse("/owner/settings/subscription?err=1", status_code=303)
    c = rows[0]
    try:
        n = max(1, int(months))
    except ValueError:
        n = 1

    # ---- FILIAL obunasi ----
    if branch_id:
        brs = supabase.table("branches").select("*").eq("id", branch_id).eq("center_id", cid).limit(1).execute().data or []
        if not brs:
            return RedirectResponse("/owner/settings/subscription?err=1", status_code=303)
        b = brs[0]
        ns = len(supabase.table("students").select("id").eq("center_id", cid).eq("branch_id", branch_id).execute().data or [])
        nt = len(supabase.table("teachers").select("id").eq("center_id", cid).eq("branch_id", branch_id).execute().data or [])
        price = data.branch_monthly_price(c, ns, nt)
        amt = price * n
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
        short, bal = _insufficient(cid, account_id, amt)
        if short:
            return RedirectResponse(f"/owner/settings/subscription?err=nomoney&bal={int(bal)}&need={int(amt)}", status_code=303)
        base_obj = {"center_id": cid, "amount": amt, "months": n,
                    "until": new_until.isoformat(), "note": f"Filial obunasi: {b.get('name')}",
                    "paid_at": datetime.now().isoformat()}
        _insert_outflow("center_payments", base_obj, account_id, method)
        supabase.table("branches").update({"sub_until": new_until.isoformat(), "suspended": False}).eq("id", branch_id).execute()
        return RedirectResponse("/owner/settings/subscription?saved=1", status_code=303)

    # ---- Markaz obunasi (filialsiz markazlar uchun) ----
    fee = data.center_monthly_fee(cid, c)
    if fee <= 0:
        return RedirectResponse("/owner/settings/subscription?err=2", status_code=303)
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
    amt = fee * n
    short, bal = _insufficient(cid, account_id, amt)
    if short:
        return RedirectResponse(f"/owner/settings/subscription?err=nomoney&bal={int(bal)}&need={int(amt)}", status_code=303)
    base_obj = {"center_id": cid, "amount": amt, "months": n,
                "until": new_until.isoformat(), "note": "Markaz egasi to'lovi",
                "paid_at": datetime.now().isoformat()}
    _insert_outflow("center_payments", base_obj, account_id, method)
    supabase.table("centers").update({"subscription_until": new_until.isoformat(), "status": "active"}).eq("id", cid).execute()
    return RedirectResponse("/owner/settings/subscription?saved=1", status_code=303)


# ====================================================================
#  XODIMLAR (administrator / qabulxona) — owner boshqaradi
# ====================================================================
@router.get("/settings/staff")
async def settings_staff(request: Request, user: dict = Depends(staff_required)):
    cid = user["center_id"]
    bid = user.get("active_branch")
    staff = (supabase.table("users").select("id, full_name, phone, role, branch_id, is_active")
             .eq("center_id", cid).eq("role", "reception").order("created_at", desc=True).execute().data) or []
    staff = _bfilter(staff, bid)   # har filialning o'z xodimlari — aralashmaydi
    try:
        branches = supabase.table("branches").select("id, name").eq("center_id", cid).order("created_at").execute().data or []
    except Exception:
        branches = []
    bname = {b["id"]: b["name"] for b in branches}
    for s in staff:
        s["branch_name"] = bname.get(s.get("branch_id"))
        s["is_active"] = s.get("is_active", True) is not False
    # Direktor (markaz egasi) — jadval tepasida ko'rsatiladi (hammaga ko'rinadi)
    try:
        crow = supabase.table("centers").select("owner_name, phone").eq("id", cid).limit(1).execute().data or []
    except Exception:
        crow = []
    director = {
        "name": (crow[0].get("owner_name") if crow else None) or user.get("center_name") or "Direktor",
        "phone": (crow[0].get("phone") if crow else None),
    }
    return templates.TemplateResponse("owner_settings_staff.html", {
        "request": request, "user": user, "active": "staff", "staff": staff,
        "branches": branches, "director": director,
        "saved": request.query_params.get("saved"), "dup": request.query_params.get("dup"),
    })


@router.post("/settings/staff/add")
async def settings_staff_add(request: Request, user: dict = Depends(owner_required),
                             full_name: str = Form(...), phone: str = Form(...), password: str = Form(...),
                             branch_id: str = Form("")):
    phone = phone.strip()
    exists = supabase.table("users").select("id").eq("phone", phone).limit(1).execute().data
    if exists:
        return RedirectResponse("/owner/settings/staff?dup=1", status_code=303)
    obj = {
        "center_id": user["center_id"], "role": "reception",
        "full_name": full_name.strip() or None, "phone": norm_phone(phone),
        "password_hash": hash_password(password.strip()), "is_active": True,
    }
    if branch_id:
        obj["branch_id"] = branch_id
    try:
        supabase.table("users").insert(obj).execute()
    except Exception:
        obj.pop("branch_id", None)
        supabase.table("users").insert(obj).execute()
    return RedirectResponse("/owner/settings/staff?saved=1", status_code=303)


@router.post("/settings/staff/{uid}/branch")
async def settings_staff_branch(uid: str, request: Request, user: dict = Depends(owner_required),
                                branch_id: str = Form("")):
    try:
        supabase.table("users").update({"branch_id": branch_id or None}) \
            .eq("id", uid).eq("center_id", user["center_id"]).eq("role", "reception").execute()
    except Exception:
        pass
    return RedirectResponse("/owner/settings/staff?saved=1", status_code=303)


@router.post("/settings/staff/{uid}/password")
async def settings_staff_password(uid: str, request: Request, user: dict = Depends(owner_required), password: str = Form(...)):
    if password.strip():
        supabase.table("users").update({"password_hash": hash_password(password.strip())}).eq("id", uid).eq("center_id", user["center_id"]).eq("role", "reception").execute()
    return RedirectResponse("/owner/settings/staff?saved=1", status_code=303)


@router.post("/settings/staff/{uid}/delete")
async def settings_staff_delete(uid: str, request: Request, user: dict = Depends(owner_required)):
    supabase.table("users").delete().eq("id", uid).eq("center_id", user["center_id"]).eq("role", "reception").execute()
    return RedirectResponse("/owner/settings/staff", status_code=303)


@router.get("/settings/staff/{uid}/perms")
async def staff_perms_page(uid: str, request: Request, user: dict = Depends(owner_required)):
    cid = user["center_id"]
    rows = (supabase.table("users").select("id, full_name, phone, permissions")
            .eq("id", uid).eq("center_id", cid).eq("role", "reception").limit(1).execute().data) or []
    if not rows:
        return RedirectResponse("/owner/settings/staff", status_code=303)
    m = rows[0]
    cur = {x.strip() for x in (m.get("permissions") or "").split(",") if x.strip()}
    return templates.TemplateResponse("owner_settings_staff_perms.html", {
        "request": request, "user": user, "active": "settings",
        "member": m, "panels": PANELS, "cur": cur,
        "saved": request.query_params.get("saved"),
    })


@router.post("/settings/staff/{uid}/perms")
async def staff_perms_save(uid: str, request: Request, user: dict = Depends(owner_required)):
    form = await request.form()
    keys = [k for k, _ in PANELS if form.get("p_" + k)]
    try:
        supabase.table("users").update({"permissions": ",".join(keys)}).eq("id", uid).eq("center_id", user["center_id"]).eq("role", "reception").execute()
    except Exception:
        pass
    return RedirectResponse(f"/owner/settings/staff/{uid}/perms?saved=1", status_code=303)


@router.post("/students/{sid}/discount")
async def student_discount(sid: str, request: Request, user: dict = Depends(staff_required),
                           group_id: str = Form(...), discount: str = Form("")):
    try:
        amt = float(str(discount).replace(" ", "").replace(",", "")) if discount.strip() else 0
    except ValueError:
        amt = 0
    data.set_discount(user["center_id"], sid, group_id, amt)
    return RedirectResponse(f"/owner/students/{sid}", status_code=303)


@router.post("/students/{sid}/share")
async def student_share(sid: str, request: Request, user: dict = Depends(staff_required)):
    cid = user["center_id"]
    rows = supabase.table("students").select("access_token, full_name").eq("id", sid).eq("center_id", cid).limit(1).execute().data or []
    if not rows:
        return RedirectResponse((getattr(request.state, "cprefix", "") or "") + "/owner/students", status_code=303)
    token = rows[0].get("access_token")
    if not token:
        import uuid as _uuid
        token = _uuid.uuid4().hex
        supabase.table("students").update({"access_token": token}).eq("id", sid).eq("center_id", cid).execute()
    link = f"{str(request.base_url).rstrip('/')}/p/{token}"
    await notify_parent(sid, f"👨‍👩‍👧 Farzandingiz {rows[0]['full_name']} uchun shaxsiy kabinet havolasi:\n{link}\n\nBu yerда davomat, baho va to'lovni kuzatishingiz mumkin.")
    return RedirectResponse((getattr(request.state, "cprefix", "") or "") + f"/owner/students/{sid}?shared=1", status_code=303)


@router.post("/students/{sid}/birthday")
async def student_birthday(sid: str, request: Request, user: dict = Depends(staff_required),
                           message: str = Form("")):
    rows = supabase.table("students").select("full_name").eq("id", sid).eq("center_id", user["center_id"]).limit(1).execute().data or []
    name = rows[0]["full_name"] if rows else "o'quvchi"
    cname = user.get("center_name") or "O'quv markaz"
    msg = message.strip() or f"🎂 Hurmatli ota-ona! {name}ni tug'ilgan kuni bilan chin dildan tabriklaymiz! Sog'lik, omad va a'lo baholar tilaymiz. — {cname}"
    await notify_parent(sid, msg)
    try:
        from datetime import date as _d
        supabase.table("students").update({"birthday_greeted_year": _d.today().year}).eq("id", sid).eq("center_id", user["center_id"]).execute()
    except Exception:
        pass
    return RedirectResponse((getattr(request.state, "cprefix", "") or "") + "/owner?bday=1", status_code=303)


@router.post("/students/{sid}/profile")
async def student_profile(sid: str, request: Request, user: dict = Depends(staff_required),
                          full_name: str = Form(...), parent_phone: str = Form(""),
                          parent_name: str = Form(""), second_phone: str = Form(""),
                          birth_date: str = Form(""), address: str = Form(""), note: str = Form(""),
                          photo: UploadFile = File(None)):
    upd = {"full_name": full_name.strip(), "parent_phone": parent_phone.strip() or None}
    extra = {"parent_name": parent_name.strip() or None, "second_phone": second_phone.strip() or None,
             "birth_date": birth_date.strip() or None, "address": address.strip() or None,
             "note": note.strip() or None}
    # Rasm yuklash (ixtiyoriy)
    if photo is not None and getattr(photo, "filename", ""):
        try:
            import os
            import uuid as _uuid
            ext = os.path.splitext(photo.filename)[1].lower()
            if ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
                fname = f"{_uuid.uuid4().hex}{ext}"
                os.makedirs("app/static/uploads", exist_ok=True)
                content = await photo.read()
                if content and len(content) <= 6 * 1024 * 1024:  # 6 MB
                    with open(f"app/static/uploads/{fname}", "wb") as f:
                        f.write(content)
                    extra["photo_url"] = f"/static/uploads/{fname}"
        except Exception:
            pass
    try:
        supabase.table("students").update(dict(upd, **extra)).eq("id", sid).eq("center_id", user["center_id"]).execute()
    except Exception:
        supabase.table("students").update(upd).eq("id", sid).eq("center_id", user["center_id"]).execute()
    return RedirectResponse(f"/owner/students/{sid}", status_code=303)


# ====================================================================
#  OMMAVIY XABAR — barcha ota-onalarga
# ====================================================================
@router.get("/announce")
async def announce_page(request: Request, user: dict = Depends(staff_required)):
    cid = user["center_id"]
    try:
        cnt = supabase.table("parents").select("id", count="exact").eq("center_id", cid).execute().count or 0
    except Exception:
        cnt = 0
    groups = supabase.table("groups").select("id, name").eq("center_id", cid).order("name").execute().data or []
    return templates.TemplateResponse("owner_announce.html", {
        "request": request, "user": user, "active": "announce",
        "parent_count": cnt, "groups": groups, "sent": request.query_params.get("sent"),
    })


@router.post("/announce")
async def announce_send(request: Request, user: dict = Depends(staff_required),
                        message: str = Form(...), target: str = Form("all"), group_id: str = Form("")):
    cid = user["center_id"]
    msg = message.strip()
    sent = 0
    if msg:
        from app.notify import notify_telegram, notify_parent
        if target == "teachers":
            try:
                teachers = supabase.table("teachers").select("telegram_id").eq("center_id", cid).execute().data or []
            except Exception:
                teachers = []
            for t in teachers:
                if t.get("telegram_id"):
                    try:
                        await notify_telegram(t["telegram_id"], f"📢 E'lon:\n{msg}")
                        sent += 1
                    except Exception:
                        pass
        elif target == "group" and group_id:
            for s in data.enrolled_students(group_id):
                if await notify_parent(s["id"], f"📢 E'lon:\n{msg}"):
                    sent += 1
        else:  # all parents
            try:
                parents = supabase.table("parents").select("telegram_id").eq("center_id", cid).execute().data or []
            except Exception:
                parents = []
            for p in parents:
                if p.get("telegram_id"):
                    try:
                        await notify_telegram(p["telegram_id"], f"📢 E'lon:\n{msg}")
                        sent += 1
                    except Exception:
                        pass
    return RedirectResponse(f"/owner/announce?sent={sent}", status_code=303)


# ====================================================================
#  PROFIL — o'z parolini almashtirish (owner)
# ====================================================================
@router.get("/settings/password")
async def owner_password_page(request: Request, user: dict = Depends(owner_required)):
    return templates.TemplateResponse("owner_settings_password.html", {
        "request": request, "user": user, "active": "settings",
        "saved": request.query_params.get("saved"), "err": request.query_params.get("err"),
    })


@router.post("/settings/password")
async def owner_password_save(request: Request, user: dict = Depends(owner_required),
                              current: str = Form(...), new: str = Form(...)):
    from app.security import verify_password, hash_password
    rows = supabase.table("users").select("password_hash").eq("id", user["id"]).limit(1).execute().data or []
    ok = rows and verify_password(current, rows[0]["password_hash"])
    if not ok or len(new.strip()) < 4:
        return RedirectResponse("/owner/settings/password?err=1", status_code=303)
    supabase.table("users").update({"password_hash": hash_password(new.strip())}).eq("id", user["id"]).execute()
    return RedirectResponse("/owner/settings/password?saved=1", status_code=303)


# ====================================================================
#  KETISH XAVFI — ketma-ket kelmagan o'quvchilar
# ====================================================================
@router.get("/risk")
async def risk_page(request: Request, user: dict = Depends(staff_required)):
    cid = user["center_id"]
    _abid = user.get("active_branch")
    streaks = data.absence_streaks(cid, threshold=3)
    students = {s["id"]: s for s in _bfilter(supabase.table("students").select("*").eq("center_id", cid).execute().data or [], _abid)}
    groups = {g["id"]: g["name"] for g in supabase.table("groups").select("id, name").eq("center_id", cid).execute().data or []}
    rows = []
    for s in streaks:
        st = students.get(s["student_id"])
        if not st or st.get("active", True) is False:
            continue
        rows.append({"sid": s["student_id"], "name": st.get("full_name", "—"),
                     "phone": st.get("parent_phone") or "—", "group": groups.get(s["group_id"], "—"),
                     "streak": s["streak"], "last_date": s["last_date"]})
    return templates.TemplateResponse("owner_risk.html", {
        "request": request, "user": user, "active": "risk", "rows": rows,
    })


# ====================================================================
#  🪙 COIN TIZIMI
# ====================================================================
@router.get("/coins")
async def coins_page(request: Request, user: dict = Depends(staff_required)):
    cid = user["center_id"]
    _abid = user.get("active_branch")
    r = coinmod.rules(cid)
    bal = coinmod.balances_for_center(cid)
    students = supabase.table("students").select("id, full_name, photo_url, branch_id").eq("center_id", cid).execute().data or []
    students = _bfilter(students, _abid)
    sname = {s["id"]: s for s in students}
    _bset = set(sname.keys())
    # faqat shu filial o'quvchilari balansi
    bal = {sid: c for sid, c in bal.items() if sid in _bset}
    # filial bo'yicha statistika
    earned = spent = 0
    try:
        for tx in (supabase.table("coin_tx").select("student_id, amount").eq("center_id", cid).execute().data or []):
            if tx.get("student_id") not in _bset:
                continue
            a = int(tx.get("amount") or 0)
            earned += a if a >= 0 else 0
            spent += -a if a < 0 else 0
    except Exception:
        pass
    st = {"earned": earned, "spent": spent, "active": earned - spent}
    # Top o'quvchilar
    top = sorted(
        [{"id": sid, "name": sname.get(sid, {}).get("full_name", "—"),
          "photo": sname.get(sid, {}).get("photo_url"), "coins": c}
         for sid, c in bal.items() if c],
        key=lambda x: x["coins"], reverse=True)[:15]
    # So'nggi tranzaksiyalar (shu filial)
    txs = [t for t in coinmod.recent_tx(cid, 120) if t.get("student_id") in _bset][:30]
    rlabel = {"attendance": "Davomat", "homework": "Baho 3", "test70": "Baho 4",
              "test90": "Baho 5", "ontime": "O'z vaqtida to'lov", "redeem": "Chegirma", "manual": "Qo'lda"}
    for t in txs:
        t["sname"] = sname.get(t.get("student_id"), {}).get("full_name", "—")
        t["rlabel"] = rlabel.get(t.get("reason"), t.get("reason") or "—")
    return templates.TemplateResponse("owner_coins.html", {
        "request": request, "user": user, "active": "coins",
        "r": r, "st": st, "top": top, "txs": txs,
        "students": sorted(students, key=lambda s: s.get("full_name") or ""),
        "saved": request.query_params.get("saved"),
    })


@router.post("/coins/rules")
async def coins_rules_save(request: Request, user: dict = Depends(owner_required),
                           attendance: str = Form("0"), homework: str = Form("0"),
                           test70: str = Form("0"), test90: str = Form("0"),
                           ontime: str = Form("0"), value: str = Form("100"),
                           enabled: str = Form("")):
    def _i(x, d=0):
        try:
            return int(float(str(x).replace(" ", "").replace(",", ".")))
        except Exception:
            return d
    new = {"attendance": _i(attendance), "homework": _i(homework), "test70": _i(test70),
           "test90": _i(test90), "ontime": _i(ontime), "value": _i(value, 100),
           "enabled": bool(enabled)}
    coinmod.save_rules(user["center_id"], new)
    return RedirectResponse("/owner/coins?saved=1", status_code=303)


@router.post("/coins/award")
async def coins_award(request: Request, user: dict = Depends(staff_required),
                      student_id: str = Form(...), amount: str = Form(...),
                      note: str = Form("")):
    try:
        amt = int(float(str(amount).replace(" ", "").replace(",", ".")))
    except Exception:
        amt = 0
    if amt and student_id:
        coinmod.award(user["center_id"], student_id, amt, "manual", note.strip() or "Qo'lda")
    return RedirectResponse("/owner/coins?saved=1", status_code=303)


# ====================================================================
#  🔔 BILDIRISHNOMALAR
# ====================================================================
@router.get("/notifications")
async def notifications_page(request: Request, user: dict = Depends(staff_required)):
    cid = user["center_id"]
    bid = user.get("active_branch")
    items = notifmod.recent(cid, bid, 60)
    unread = sum(1 for n in items if not n.get("read_at"))
    # sahifa ochilishi bilan — hammasi o'qilgan deb hisoblanadi
    notifmod.mark_all_read(cid, bid)
    user = dict(user); user["notif_unread"] = 0
    return templates.TemplateResponse("owner_notifications.html", {
        "request": request, "user": user, "active": "notifications",
        "items": items, "unread": unread,
    })


@router.post("/notifications/read")
async def notifications_read(request: Request, user: dict = Depends(staff_required)):
    notifmod.mark_all_read(user["center_id"], user.get("active_branch"))
    return RedirectResponse("/owner/notifications", status_code=303)


# ====================================================================
#  🧾 XARAJAT SO'ROVI (administrator so'raydi -> egasi tasdiqlaydi)
# ====================================================================
@router.get("/expense-requests")
async def expense_requests_page(request: Request, user: dict = Depends(staff_required)):
    cid = user["center_id"]
    try:
        items = supabase.table("expense_requests").select("*").eq("center_id", cid).order("created_at", desc=True).limit(120).execute().data or []
    except Exception:
        items = []
    items = _bfilter(items, user.get("active_branch"))
    pending = [x for x in items if x.get("status") == "pending"]
    done = [x for x in items if x.get("status") != "pending"]
    return templates.TemplateResponse("owner_expense_requests.html", {
        "request": request, "user": user, "active": "expense_requests",
        "pending": pending, "done": done, "is_owner": user.get("is_owner"),
        "saved": request.query_params.get("saved"),
    })


@router.post("/expense-requests/submit")
async def expense_request_submit(request: Request, user: dict = Depends(staff_required),
                                 amount: str = Form(...), reason: str = Form("")):
    try:
        amt = float(str(amount).replace(" ", "").replace(",", "."))
    except ValueError:
        amt = 0
    bid = user.get("active_branch")
    if amt > 0:
        obj = {"center_id": user["center_id"], "requested_by": user.get("id"),
               "requested_name": user.get("name"), "amount": amt,
               "reason": reason.strip() or None, "status": "pending"}
        if bid:
            obj["branch_id"] = bid
        try:
            supabase.table("expense_requests").insert(obj).execute()
        except Exception:
            obj.pop("branch_id", None)
            try:
                supabase.table("expense_requests").insert(obj).execute()
            except Exception:
                pass
        notifmod.notify(user["center_id"], "Yangi xarajat so'rovi",
                        f"{user.get('name')}: {int(amt):,} so'm — {reason.strip() or 'sababsiz'}".replace(",", " "),
                        "expense", branch_id=bid)
    return RedirectResponse("/owner/expense-requests?saved=1", status_code=303)


@router.post("/expense-requests/{rid}/decide")
async def expense_request_decide(rid: str, request: Request, user: dict = Depends(owner_required),
                                 decision: str = Form(...), account_id: str = Form("")):
    cid = user["center_id"]
    rows = supabase.table("expense_requests").select("*").eq("id", rid).eq("center_id", cid).limit(1).execute().data or []
    if not rows:
        return RedirectResponse("/owner/expense-requests", status_code=303)
    req = rows[0]
    if req.get("status") != "pending":
        return RedirectResponse("/owner/expense-requests", status_code=303)
    rbid = req.get("branch_id")

    if decision == "approve":
        amt = float(req.get("amount") or 0)
        short, bal = _insufficient(cid, account_id, amt)
        if short:
            return RedirectResponse(f"/owner/expense-requests?err=nomoney", status_code=303)
        obj = {"center_id": cid, "category": "So'rov: " + (req.get("reason") or "Xarajat"),
               "amount": amt, "note": f"Administrator so'rovi ({req.get('requested_name') or '—'})"}
        if rbid:
            obj["branch_id"] = rbid
        _insert_outflow("expenses", obj, account_id, "")
        supabase.table("expense_requests").update({"status": "approved", "decided_at": datetime.now().isoformat(),
                                                   "account_id": account_id or None}).eq("id", rid).execute()
        notifmod.notify(cid, "Xarajat so'rovi tasdiqlandi",
                        f"{int(amt):,} so'm — {req.get('reason') or ''}".replace(",", " "), "success", branch_id=rbid)
    else:
        supabase.table("expense_requests").update({"status": "rejected", "decided_at": datetime.now().isoformat()}).eq("id", rid).execute()
        notifmod.notify(cid, "Xarajat so'rovi rad etildi",
                        f"{int(float(req.get('amount') or 0)):,} so'm — {req.get('reason') or ''}".replace(",", " "), "warning", branch_id=rbid)
    return RedirectResponse("/owner/expense-requests?saved=1", status_code=303)


# ====================================================================
#  📅 BAYRAM KUNLARI
# ====================================================================
def _holiday_dates(cid: str) -> dict:
    """{ 'YYYY-MM-DD': 'nomi' } — markazning bayram kunlari."""
    try:
        rows = supabase.table("holidays").select("date, name").eq("center_id", cid).execute().data or []
        return {str(r["date"])[:10]: r["name"] for r in rows}
    except Exception:
        return {}


@router.get("/holidays")
async def holidays_page(request: Request, user: dict = Depends(staff_required)):
    cid = user["center_id"]
    try:
        year = int(request.query_params.get("year") or date.today().year)
    except ValueError:
        year = date.today().year
    try:
        rows = supabase.table("holidays").select("*").eq("center_id", cid).order("date").execute().data or []
    except Exception:
        rows = []
    items = [h for h in rows if str(h.get("date", ""))[:4] == str(year)]
    years = sorted({int(str(h["date"])[:4]) for h in rows} | {date.today().year, date.today().year + 1})
    return templates.TemplateResponse("owner_holidays.html", {
        "request": request, "user": user, "active": "holidays",
        "items": items, "year": year, "years": years,
        "saved": request.query_params.get("saved"),
    })


@router.post("/holidays/add")
async def holidays_add(request: Request, user: dict = Depends(staff_required),
                       hdate: str = Form(...), name: str = Form(...)):
    cid = user["center_id"]
    if hdate.strip() and name.strip():
        obj = {"center_id": cid, "date": hdate.strip(), "name": name.strip()}
        try:
            supabase.table("holidays").insert(obj).execute()
        except Exception:
            # bir xil sana bo'lsa — yangilaymiz
            try:
                supabase.table("holidays").update({"name": name.strip()}).eq("center_id", cid).eq("date", hdate.strip()).execute()
            except Exception:
                pass
    y = hdate.strip()[:4] if hdate.strip() else date.today().year
    return RedirectResponse(f"/owner/holidays?year={y}&saved=1", status_code=303)


@router.post("/holidays/{hid}/delete")
async def holidays_delete(hid: str, request: Request, user: dict = Depends(staff_required)):
    try:
        supabase.table("holidays").delete().eq("id", hid).eq("center_id", user["center_id"]).execute()
    except Exception:
        pass
    return RedirectResponse("/owner/holidays", status_code=303)


# ====================================================================
#  📈 ANALITIKA (chuqur)
# ====================================================================
@router.get("/analytics")
async def analytics_page(request: Request, user: dict = Depends(staff_required)):
    cid = user["center_id"]
    now_ym = data.cur_ym()
    sel_month = request.query_params.get("month") or now_ym
    months = [(ym, _ym_label(ym)) for ym in (data.add_months(now_ym, k) for k in range(-11, 1))]

    # ===== GLOBAL moliyaviy ko'rsatkichlar (tanlangan oy, BARCHA filiallar) =====
    income = data.income_for_month(cid, sel_month)
    expenses = data.expenses_for_month(cid, sel_month)
    payouts = sum(data.payouts_for_month(cid, sel_month).values())
    refund = 0.0
    profit = income - expenses - payouts
    fin = {"income": income, "refund": refund, "payouts": payouts,
           "expenses": expenses, "profit": profit}
    _fmax = max(1.0, income, expenses, payouts)
    fin_bars = [
        {"label": "Tushum", "val": income, "pct": round(income * 100 / _fmax, 1), "color": "#2f6df6"},
        {"label": "O'qit. ulush", "val": payouts, "pct": round(payouts * 100 / _fmax, 1), "color": "#8b5cf6"},
        {"label": "Xarajat", "val": expenses, "pct": round(expenses * 100 / _fmax, 1), "color": "#ef4444"},
    ]

    # ===== Filiallar foydasi (tanlangan oy) =====
    branch_profit = []
    try:
        brs = supabase.table("branches").select("id, name").eq("center_id", cid).order("created_at").execute().data or []
    except Exception:
        brs = []
    for b in brs:
        try:
            bst = {s["id"] for s in supabase.table("students").select("id").eq("center_id", cid).eq("branch_id", b["id"]).execute().data or []}
            bte = {t["id"] for t in supabase.table("teachers").select("id").eq("center_id", cid).eq("branch_id", b["id"]).execute().data or []}
        except Exception:
            bst, bte = set(), set()
        inc = data.income_for_month(cid, sel_month, bst)
        exp = data.expenses_for_month(cid, sel_month, b["id"])
        pay = sum(data.payouts_for_month(cid, sel_month, bte).values())
        branch_profit.append({"name": b["name"], "income": inc,
                              "expense": exp + pay, "profit": inc - exp - pay})
    branch_profit.sort(key=lambda x: -x["profit"])
    _bpmax = max([1.0] + [abs(b["profit"]) for b in branch_profit])
    for b in branch_profit:
        b["bar"] = round(max(0, b["profit"]) * 100 / _bpmax, 1)

    # ===== So'nggi tranzaksiyalar (tanlangan oy) =====
    ms, me = data.month_bounds(sel_month)
    recent_tx = []
    try:
        snm = {s["id"]: s["full_name"] for s in supabase.table("students").select("id, full_name").eq("center_id", cid).execute().data or []}
    except Exception:
        snm = {}
    try:
        for p in (supabase.table("payments").select("student_id, amount, paid_at, method")
                  .eq("center_id", cid).eq("status", "paid").gte("paid_at", ms).lt("paid_at", me)
                  .order("paid_at", desc=True).limit(15).execute().data or []):
            recent_tx.append({"kind": "in", "title": snm.get(p.get("student_id"), "To'lov"),
                              "amount": float(p.get("amount") or 0),
                              "at": (p.get("paid_at") or "")[:16].replace("T", " "),
                              "method": p.get("method") or ""})
    except Exception:
        pass
    try:
        for e in (supabase.table("expenses").select("category, amount, spent_at")
                  .eq("center_id", cid).gte("spent_at", ms).lt("spent_at", me)
                  .order("spent_at", desc=True).limit(10).execute().data or []):
            recent_tx.append({"kind": "out", "title": e.get("category") or "Xarajat",
                              "amount": float(e.get("amount") or 0),
                              "at": (e.get("spent_at") or "")[:16].replace("T", " "), "method": ""})
    except Exception:
        pass
    recent_tx.sort(key=lambda x: x["at"], reverse=True)
    recent_tx = recent_tx[:18]

    # ===== Lidlar voronkasi (GLOBAL) =====
    try:
        leads = supabase.table("leads").select("status").eq("center_id", cid).execute().data or []
    except Exception:
        leads = []
    lc = {}
    for l in leads:
        st = l.get("status") or "new"
        lc[st] = lc.get(st, 0) + 1
    total_leads = len(leads)
    trial_n = lc.get("trial", 0)
    enrolled_n = lc.get("enrolled", 0)
    funnel = {
        "total": total_leads, "new": lc.get("new", 0), "contacted": lc.get("contacted", 0),
        "trial": trial_n, "enrolled": enrolled_n, "lost": lc.get("lost", 0),
        "lead_conv": round(enrolled_n * 100 / total_leads) if total_leads else 0,
        "trial_conv": round(enrolled_n * 100 / trial_n) if trial_n else 0,
    }

    # ===== O'quvchilar retention/churn (GLOBAL) =====
    students = supabase.table("students").select("id, active").eq("center_id", cid).execute().data or []
    active_n = sum(1 for s in students if s.get("active", True) is not False)
    churned_n = sum(1 for s in students if s.get("active", True) is False)
    total_students = len(students)
    retention = round(active_n * 100 / total_students) if total_students else 0
    churn = round(churned_n * 100 / total_students) if total_students else 0

    # ===== 6 oylik tendensiya (GLOBAL) =====
    trend = []
    max_income = 1
    for k in range(-5, 1):
        ym = data.add_months(now_ym, k)
        inc = data.income_for_month(cid, ym)
        exp = data.expenses_for_month(cid, ym)
        pay = sum(data.payouts_for_month(cid, ym).values())
        trend.append({"ym": ym, "label": _ym_label(ym), "income": inc,
                      "expense": exp + pay, "profit": inc - exp - pay})
        max_income = max(max_income, inc, exp + pay)
    for t in trend:
        t["bar_income"] = round(t["income"] * 100 / max_income, 1)
        t["bar_expense"] = round(t["expense"] * 100 / max_income, 1)

    # ===== Davomat (GLOBAL) =====
    try:
        att = supabase.table("attendance").select("status").eq("center_id", cid).execute().data or []
    except Exception:
        att = []
    present = sum(1 for a in att if a.get("status") in ("present", "late"))
    att_rate = round(present * 100 / len(att)) if att else None

    # ===== Qarzdorlik (GLOBAL) =====
    debt_map = data.center_debtors(cid)
    debtors_n = sum(1 for v in debt_map.values() if v > 0)
    total_debt = sum(v for v in debt_map.values() if v > 0)

    # ===== Coin (GLOBAL) =====
    c_earned = c_spent = 0
    try:
        for tx in (supabase.table("coin_tx").select("amount").eq("center_id", cid).execute().data or []):
            a = int(tx.get("amount") or 0)
            c_earned += a if a >= 0 else 0
            c_spent += -a if a < 0 else 0
    except Exception:
        pass
    coin_stats = {"earned": c_earned, "spent": c_spent, "active": c_earned - c_spent}

    cur = trend[-1] if trend else {"income": 0, "expense": 0, "profit": 0}
    return templates.TemplateResponse("owner_analytics.html", {
        "request": request, "user": user, "active": "analytics",
        "sel_month": sel_month, "months": months, "fin": fin, "fin_bars": fin_bars,
        "branch_profit": branch_profit, "recent_tx": recent_tx,
        "funnel": funnel, "active_n": active_n, "churned_n": churned_n,
        "total_students": total_students, "retention": retention, "churn": churn,
        "trend": trend, "att_rate": att_rate, "debtors_n": debtors_n,
        "total_debt": total_debt, "coin_stats": coin_stats, "cur": cur,
        "month_label": _ym_label(sel_month),
    })


# ====================================================================
#  🏢 FILIALLAR
# ====================================================================
def _bfilter(rows, bid, key="branch_id"):
    """Filial tanlangan bo'lsa — faqat o'sha filial yozuvlari. None = hammasi."""
    if not bid:
        return rows
    return [r for r in rows if r.get(key) == bid]


@router.post("/branch/select")
async def branch_select(request: Request, user: dict = Depends(owner_required),
                        branch_id: str = Form("")):
    set_active_branch(request, user["center_id"], branch_id or None)
    back = request.headers.get("referer") or "/owner"
    return RedirectResponse(back, status_code=303)


@router.get("/branches")
async def branches_page(request: Request, user: dict = Depends(owner_required)):
    cid = user["center_id"]
    try:
        branches = supabase.table("branches").select("*").eq("center_id", cid).order("created_at").execute().data or []
    except Exception:
        branches = []
    # har filialdagi o'quvchi/guruh/o'qituvchi soni
    def _counts(tbl):
        out = {}
        try:
            for r in (supabase.table(tbl).select("branch_id").eq("center_id", cid).execute().data or []):
                out[r.get("branch_id")] = out.get(r.get("branch_id"), 0) + 1
        except Exception:
            pass
        return out
    sc, gc, tc = _counts("students"), _counts("groups"), _counts("teachers")
    for b in branches:
        b["students"] = sc.get(b["id"], 0)
        b["groups"] = gc.get(b["id"], 0)
        b["teachers"] = tc.get(b["id"], 0)
    unassigned = {"students": sc.get(None, 0), "groups": gc.get(None, 0), "teachers": tc.get(None, 0)}
    return templates.TemplateResponse("owner_branches.html", {
        "request": request, "user": user, "active": "branches",
        "branches": branches, "unassigned": unassigned,
        "saved": request.query_params.get("saved"),
    })


@router.post("/branches/add")
async def branches_add(request: Request, user: dict = Depends(owner_required),
                       name: str = Form(...), address: str = Form("")):
    if name.strip():
        try:
            supabase.table("branches").insert({
                "center_id": user["center_id"], "name": name.strip(),
                "address": address.strip() or None,
            }).execute()
        except Exception:
            pass
    return RedirectResponse("/owner/branches?saved=1", status_code=303)


@router.post("/branches/{bid}/edit")
async def branches_edit(bid: str, request: Request, user: dict = Depends(owner_required),
                        name: str = Form(...), address: str = Form("")):
    try:
        supabase.table("branches").update({"name": name.strip(), "address": address.strip() or None}) \
            .eq("id", bid).eq("center_id", user["center_id"]).execute()
    except Exception:
        pass
    return RedirectResponse("/owner/branches?saved=1", status_code=303)


@router.post("/branches/{bid}/delete")
async def branches_delete(bid: str, request: Request, user: dict = Depends(owner_required)):
    cid = user["center_id"]
    # yozuvlarni "umumiy"ga qaytaramiz (branch_id = NULL), keyin filialni o'chiramiz
    for tbl in ("students", "groups", "teachers", "rooms", "leads", "expenses"):
        try:
            supabase.table(tbl).update({"branch_id": None}).eq("center_id", cid).eq("branch_id", bid).execute()
        except Exception:
            pass
    try:
        supabase.table("branches").delete().eq("id", bid).eq("center_id", cid).execute()
    except Exception:
        pass
    return RedirectResponse("/owner/branches?saved=1", status_code=303)
