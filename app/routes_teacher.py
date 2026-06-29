"""O'QITUVCHI WEB PANELI — botdan ko'ra qulay.

  /teacher              -> bosh sahifa (guruhlarim)
  /teacher/attendance   -> davomat (bir sahifada hammasi, bir tugmada saqlash)
  /teacher/grades       -> baho (jadvalda hamma o'quvchiga birato'la)
  /teacher/lesson       -> bugungi dars (mavzu + uy vazifa -> ota-onalarga)

O'qituvchi web'da amal qilganda ham ota-onaga Telegram xabari ketadi.
"""
from datetime import date

from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse

from app.db import supabase
from app.deps import templates, teacher_required
from app.notify import notify_parent
from app import data

router = APIRouter(prefix="/teacher")

COMMENTS = ["", "Faol edi", "Vazifa qilmadi", "Yaxshilanyapti", "Diqqat kerak"]


def _log_edit(cid, tid, kind, sid, gid, d, old, new):
    """O'qituvchi o'zgartirishini owner ko'rishi uchun yozib qo'yamiz."""
    try:
        supabase.table("record_edits").insert({
            "center_id": cid, "teacher_id": tid, "kind": kind,
            "student_id": sid, "group_id": gid, "date": d,
            "old_value": str(old), "new_value": str(new),
        }).execute()
    except Exception:
        pass


def _my_groups(tid: str):
    return supabase.table("groups").select(
        "id, name, subject, schedule_days, schedule_time"
    ).eq("teacher_id", tid).order("name").execute().data or []


# ====================================================================
#  BOSH SAHIFA
# ====================================================================
@router.get("")
async def dashboard(request: Request, user: dict = Depends(teacher_required)):
    tid = user["id"]
    groups = _my_groups(tid)
    for g in groups:
        g["count"] = len(data.enrolled_students(g["id"]))

    # O'z maoshi (shu oy)
    trow = supabase.table("teachers").select("*").eq("id", tid).limit(1).execute().data or []
    cid = (trow[0].get("center_id") if trow else None) or user.get("center_id")
    pct = float(trow[0].get("commission_percent") or 0) if trow else 0
    salary = None
    if cid:
        collected = data.collected_by_group(cid)
        coll = sum(collected.get(g["id"], 0.0) for g in groups)
        earned = coll * pct / 100
        paid = data.payouts_this_month(cid).get(tid, 0.0)
        salary = {"collected": coll, "pct": pct, "earned": earned,
                  "paid": paid, "remaining": earned - paid}

    return templates.TemplateResponse("teacher_dashboard.html", {
        "request": request, "user": user, "active": "dashboard",
        "groups": groups, "today": date.today().isoformat(), "salary": salary,
    })


# ====================================================================
#  DAVOMAT
# ====================================================================
@router.get("/attendance")
async def attendance_page(request: Request, user: dict = Depends(teacher_required)):
    groups = _my_groups(user["id"])
    sel = request.query_params.get("group") or (groups[0]["id"] if groups else "")
    d = request.query_params.get("date") or date.today().isoformat()
    edit = request.query_params.get("edit")

    students = []
    has_records = False
    if sel:
        students = data.enrolled_students(sel)
        existing = {
            a["student_id"]: a["status"]
            for a in supabase.table("attendance").select("student_id, status").eq("group_id", sel).eq("date", d).execute().data or []
        }
        has_records = bool(existing)
        for s in students:
            st = existing.get(s["id"])
            s["status"] = st if st in ("present", "absent") else "present"

    return templates.TemplateResponse("teacher_attendance.html", {
        "request": request, "user": user, "active": "attendance",
        "groups": groups, "sel": sel, "date": d, "students": students,
        "locked": has_records and not edit, "saved": request.query_params.get("saved"),
    })


@router.post("/attendance")
async def attendance_save(request: Request, user: dict = Depends(teacher_required)):
    form = await request.form()
    gid = form.get("group_id")
    d = form.get("date") or date.today().isoformat()
    cid = user["center_id"]

    students = data.enrolled_students(gid)
    existing = {
        a["student_id"]: a
        for a in supabase.table("attendance").select("id, student_id, status").eq("group_id", gid).eq("date", d).execute().data or []
    }

    for s in students:
        new_status = form.get(f"status_{s['id']}")
        if new_status not in ("present", "absent"):
            continue
        ex = existing.get(s["id"])
        changed = False
        if ex:
            if ex["status"] != new_status:
                _log_edit(cid, user["id"], "attendance", s["id"], gid, d, ex["status"], new_status)
                supabase.table("attendance").update({"status": new_status}).eq("id", ex["id"]).execute()
                changed = True
        else:
            supabase.table("attendance").insert({
                "center_id": cid, "group_id": gid, "student_id": s["id"],
                "date": d, "status": new_status,
            }).execute()
            changed = True
        # faqat o'zgargan bo'lsa ota-onaga xabar (qayta-qayta yubormaslik uchun)
        if changed:
            if new_status == "present":
                await notify_parent(s["id"], f"✅ {s['full_name']} darsga keldi ({d}).")
            else:
                await notify_parent(s["id"], f"❌ {s['full_name']} bugun darsga kelmadi ({d}).")

    return RedirectResponse(f"/teacher/attendance?group={gid}&date={d}&saved=1", status_code=303)


# ====================================================================
#  BAHO — jadvalda hamma o'quvchiga birato'la
# ====================================================================
@router.get("/grades")
async def grades_page(request: Request, user: dict = Depends(teacher_required)):
    groups = _my_groups(user["id"])
    sel = request.query_params.get("group") or (groups[0]["id"] if groups else "")
    d = request.query_params.get("date") or date.today().isoformat()
    edit = request.query_params.get("edit")
    students = []
    has_records = False
    if sel:
        students = data.enrolled_students(sel)
        existing = {}
        try:
            for r in supabase.table("grades").select("id, student_id, grade, comment").eq("group_id", sel).eq("date", d).execute().data or []:
                existing[r["student_id"]] = r
        except Exception:
            existing = {}
        has_records = bool(existing)
        for s in students:
            e = existing.get(s["id"])
            s["grade"] = e["grade"] if e else ""
            s["comment"] = (e.get("comment") if e else "") or ""
    return templates.TemplateResponse("teacher_grades.html", {
        "request": request, "user": user, "active": "grades",
        "groups": groups, "sel": sel, "date": d, "students": students,
        "comments": COMMENTS, "locked": has_records and not edit,
        "saved": request.query_params.get("saved"),
    })


@router.post("/grades")
async def grades_save(request: Request, user: dict = Depends(teacher_required)):
    form = await request.form()
    gid = form.get("group_id")
    d = form.get("date") or date.today().isoformat()
    cid = user["center_id"]
    tid = user["id"]

    students = data.enrolled_students(gid)
    existing = {}
    try:
        for r in supabase.table("grades").select("id, student_id, grade, comment").eq("group_id", gid).eq("date", d).execute().data or []:
            existing[r["student_id"]] = r
    except Exception:
        existing = {}

    saved = 0
    for s in students:
        g = form.get(f"grade_{s['id']}")
        if not g:
            continue
        comment = (form.get(f"comment_{s['id']}") or "").strip()
        ex = existing.get(s["id"])
        if ex:
            if str(ex.get("grade")) != str(g) or (ex.get("comment") or "") != comment:
                _log_edit(cid, tid, "grade", s["id"], gid, d, ex.get("grade"), g)
                supabase.table("grades").update({"grade": int(g), "comment": comment or None}).eq("id", ex["id"]).execute()
                txt = f"📝 {s['full_name']} uchun baho yangilandi: {g}."
                if comment:
                    txt += f"\nIzoh: {comment}"
                await notify_parent(s["id"], txt)
                saved += 1
        else:
            supabase.table("grades").insert({
                "center_id": cid, "student_id": s["id"], "group_id": gid, "teacher_id": tid,
                "grade": int(g), "comment": comment or None, "date": d,
            }).execute()
            txt = f"📝 {s['full_name']} uchun baho: {g}."
            if comment:
                txt += f"\nIzoh: {comment}"
            await notify_parent(s["id"], txt)
            saved += 1

    return RedirectResponse(f"/teacher/grades?group={gid}&date={d}&saved={saved}", status_code=303)


# ====================================================================
#  BUGUNGI DARS / KUNLIK XULOSA
# ====================================================================
@router.get("/lesson")
async def lesson_page(request: Request, user: dict = Depends(teacher_required)):
    groups = _my_groups(user["id"])
    sel = request.query_params.get("group") or (groups[0]["id"] if groups else "")
    d = request.query_params.get("date") or date.today().isoformat()
    topic = homework = ""
    if sel:
        try:
            rows = supabase.table("lessons").select("topic, homework").eq("group_id", sel).eq("date", d).order("created_at", desc=True).limit(1).execute().data or []
            if rows:
                topic = rows[0].get("topic") or ""
                homework = rows[0].get("homework") or ""
        except Exception:
            pass
    return templates.TemplateResponse("teacher_lesson.html", {
        "request": request, "user": user, "active": "lesson",
        "groups": groups, "sel": sel, "date": d, "topic": topic, "homework": homework,
        "saved": request.query_params.get("saved"),
    })


@router.post("/lesson")
async def lesson_save(request: Request, user: dict = Depends(teacher_required)):
    form = await request.form()
    gid = form.get("group_id")
    d = form.get("date") or date.today().isoformat()
    topic = (form.get("topic") or "").strip()
    homework = (form.get("homework") or "").strip()
    cid = user["center_id"]
    tid = user["id"]

    supabase.table("lessons").insert({
        "center_id": cid, "group_id": gid, "teacher_id": tid,
        "topic": topic or None, "homework": homework or None, "date": d,
    }).execute()

    students = data.enrolled_students(gid)
    msg = f"📚 Dars ({d})\nMavzu: {topic}"
    if homework:
        msg += f"\n📝 Uyga vazifa: {homework}"
    for s in students:
        await notify_parent(s["id"], msg)

    return RedirectResponse(f"/teacher/lesson?group={gid}&date={d}&saved={len(students)}", status_code=303)
