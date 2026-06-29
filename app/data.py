"""Umumiy ma'lumot yordamchilari — qatnashuv (enrollments), to'lov, foiz.

Har bir funksiya migratsiya QILINMAGAN holatда ham ishlaydi (eski group_id'ga
qaytadi), shuning uchun schema_v5 RUN qilinmasa ham sahifa qulamaydi.
"""
from datetime import date

from app.db import supabase


def month_start() -> str:
    return date.today().replace(day=1).isoformat()


def enrolled_students(group_id: str):
    """Guruhga (fanga) yozilgan o'quvchilar [id, full_name, parent_phone]."""
    try:
        ids = [r["student_id"] for r in
               supabase.table("enrollments").select("student_id").eq("group_id", group_id).execute().data or []]
        rows = (supabase.table("students").select("id, full_name, parent_phone")
                .in_("id", ids).execute().data or []) if ids else []
    except Exception:
        rows = supabase.table("students").select("id, full_name, parent_phone").eq("group_id", group_id).execute().data or []
    return sorted(rows, key=lambda s: (s.get("full_name") or "").lower())


def center_enrollments(cid: str):
    """Markazdagi barcha (student_id, group_id) juftliklari."""
    try:
        return supabase.table("enrollments").select("student_id, group_id").eq("center_id", cid).execute().data or []
    except Exception:
        st = supabase.table("students").select("id, group_id").eq("center_id", cid).execute().data or []
        return [{"student_id": s["id"], "group_id": s["group_id"]} for s in st if s.get("group_id")]


def is_enrolled(student_id: str, group_id: str) -> bool:
    try:
        r = supabase.table("enrollments").select("id").eq("student_id", student_id).eq("group_id", group_id).limit(1).execute().data
        return bool(r)
    except Exception:
        r = supabase.table("students").select("id").eq("id", student_id).eq("group_id", group_id).limit(1).execute().data
        return bool(r)


def add_enrollment(cid: str, student_id: str, group_id: str):
    try:
        if not is_enrolled(student_id, group_id):
            supabase.table("enrollments").insert({"center_id": cid, "student_id": student_id, "group_id": group_id}).execute()
    except Exception:
        supabase.table("students").update({"group_id": group_id}).eq("id", student_id).execute()


def remove_enrollment(cid: str, student_id: str, group_id: str):
    try:
        supabase.table("enrollments").delete().eq("center_id", cid).eq("student_id", student_id).eq("group_id", group_id).execute()
    except Exception:
        supabase.table("students").update({"group_id": None}).eq("id", student_id).execute()


def group_fees(cid: str) -> dict:
    """group_id -> oylik to'lov. select('*') — ustun yo'q bo'lsa ham yiqilmaydi."""
    rows = supabase.table("groups").select("*").eq("center_id", cid).execute().data or []
    return {g["id"]: float(g.get("monthly_fee") or 0) for g in rows}


def payouts_this_month(cid: str) -> dict:
    """teacher_id -> shu oy o'qituvchiga berilgan oylik (jami)."""
    try:
        rows = (supabase.table("teacher_payouts").select("teacher_id, amount")
                .eq("center_id", cid).gte("paid_at", month_start()).execute().data) or []
    except Exception:
        rows = []
    m = {}
    for p in rows:
        m[p["teacher_id"]] = m.get(p["teacher_id"], 0.0) + float(p["amount"] or 0)
    return m


def paid_by_pair(cid: str) -> dict:
    """(student_id, group_id) -> shu oy to'langan summa."""
    try:
        rows = (supabase.table("payments").select("student_id, group_id, amount")
                .eq("center_id", cid).eq("status", "paid").gte("paid_at", month_start()).execute().data) or []
    except Exception:
        rows = (supabase.table("payments").select("student_id, amount")
                .eq("center_id", cid).eq("status", "paid").gte("paid_at", month_start()).execute().data) or []
        for r in rows:
            r["group_id"] = None
    m = {}
    for p in rows:
        key = (p["student_id"], p.get("group_id"))
        m[key] = m.get(key, 0.0) + float(p["amount"] or 0)
    return m


def collected_by_group(cid: str) -> dict:
    """group_id -> shu oy yig'ilgan summa (o'qituvchi foizi uchun)."""
    try:
        rows = (supabase.table("payments").select("group_id, amount")
                .eq("center_id", cid).eq("status", "paid").gte("paid_at", month_start()).execute().data) or []
    except Exception:
        rows = []
    m = {}
    for p in rows:
        m[p.get("group_id")] = m.get(p.get("group_id"), 0.0) + float(p["amount"] or 0)
    return m


# ---- KASSA (kirim / chiqim) -----------------------------------------
def income_this_month(cid: str) -> float:
    """Shu oy yig'ilgan to'lovlar (kirim)."""
    return income_for_month(cid, cur_ym())


def expenses_this_month(cid: str) -> float:
    """Shu oy chiqimlar (xarajatlar)."""
    return expenses_for_month(cid, cur_ym())


def payouts_total_this_month(cid: str) -> float:
    """Shu oy o'qituvchilarga berilgan oylik (jami)."""
    return sum(payouts_for_month(cid, cur_ym()).values())


def active_student_ids(cid: str) -> set:
    """Faol (ketmagan) o'quvchilar id-lari. 'active' ustuni yo'q bo'lsa hammasi faol."""
    rows = supabase.table("students").select("*").eq("center_id", cid).execute().data or []
    return {r["id"] for r in rows if r.get("active", True) is not False}


# =====================================================================
#  OYLIK TO'LOV MODELI — har oy uchun balans/taqsimot
# =====================================================================
def cur_ym() -> str:
    return date.today().strftime("%Y-%m")


def ym_of(s) -> str:
    return (s or "")[:7]


def add_months(ym: str, n: int) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    idx = y * 12 + (m - 1) + n
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def months_range(a: str, b: str) -> list:
    """a..b (inclusive), 'YYYY-MM'."""
    out, cur = [], a
    if not a or not b or a > b:
        return [a] if a and a == b else ([] if not a else [a])
    while cur <= b and len(out) < 240:
        out.append(cur)
        cur = add_months(cur, 1)
    return out


def month_bounds(ym: str):
    return ym + "-01", add_months(ym, 1) + "-01"


def income_for_month(cid: str, ym: str) -> float:
    s, e = month_bounds(ym)
    try:
        rows = (supabase.table("payments").select("amount").eq("center_id", cid)
                .eq("status", "paid").gte("paid_at", s).lt("paid_at", e).execute().data) or []
    except Exception:
        rows = []
    return sum(float(r["amount"] or 0) for r in rows)


def expenses_for_month(cid: str, ym: str) -> float:
    s, e = month_bounds(ym)
    try:
        rows = (supabase.table("expenses").select("amount").eq("center_id", cid)
                .gte("spent_at", s).lt("spent_at", e).execute().data) or []
    except Exception:
        rows = []
    return sum(float(r["amount"] or 0) for r in rows)


def payouts_for_month(cid: str, ym: str) -> dict:
    s, e = month_bounds(ym)
    try:
        rows = (supabase.table("teacher_payouts").select("teacher_id, amount").eq("center_id", cid)
                .gte("paid_at", s).lt("paid_at", e).execute().data) or []
    except Exception:
        rows = []
    m = {}
    for p in rows:
        m[p["teacher_id"]] = m.get(p["teacher_id"], 0.0) + float(p["amount"] or 0)
    return m


def paid_total_by_pair(cid: str) -> dict:
    """(student_id, group_id) -> umrbod jami to'langan (oylik balans uchun)."""
    try:
        rows = (supabase.table("payments").select("student_id, group_id, amount")
                .eq("center_id", cid).eq("status", "paid").execute().data) or []
    except Exception:
        rows = []
    m = {}
    for p in rows:
        k = (p["student_id"], p.get("group_id"))
        m[k] = m.get(k, 0.0) + float(p["amount"] or 0)
    return m


def enrollment_starts(cid: str) -> dict:
    """(student_id, group_id) -> boshlangan oy ('YYYY-MM')."""
    try:
        rows = (supabase.table("enrollments").select("student_id, group_id, created_at")
                .eq("center_id", cid).execute().data) or []
        return {(r["student_id"], r["group_id"]): (ym_of(r.get("created_at")) or cur_ym()) for r in rows}
    except Exception:
        return {}


def alloc_for_month(start_ym, now_ym, fee, total_paid, target_ym):
    """target oy uchun (taqsimlangan summa, holat).
    Qoplangan = full, qisman = partial, qoplanmagan = unpaid. (kelajak/o'tmish farqi yo'q)
    holat: full / partial / unpaid / before / none"""
    if fee <= 0:
        return 0.0, "none"
    if not start_ym or target_ym < start_ym:
        return 0.0, "before"
    remaining = total_paid
    alloc = 0.0
    for ym in months_range(start_ym, target_ym):
        a = min(remaining, fee)
        remaining -= a
        if ym == target_ym:
            alloc = a
    if alloc >= fee:
        return alloc, "full"
    if alloc > 0:
        return alloc, "partial"
    return 0.0, "unpaid"


def pair_summary(start_ym, now_ym, fee, total_paid):
    """Bir (o'quvchi×fan) bo'yicha: qarz, oldindan to'langan oylar soni."""
    if fee <= 0:
        return {"debt": 0.0, "ahead": 0, "due_months": 0}
    due_months = len(months_range(start_ym, now_ym))
    due_total = due_months * fee
    debt = max(0.0, due_total - total_paid)
    extra = total_paid - due_total
    ahead = int(extra // fee) if extra > 0 else 0
    return {"debt": debt, "ahead": ahead, "due_months": due_months}


# ---- Chegirmali narx (fan bo'yicha) ---------------------------------
def pair_fees(cid: str) -> dict:
    """(student_id, group_id) -> chegirmadan keyingi oylik to'lov."""
    gfees = group_fees(cid)
    disc = {}
    try:
        for e in supabase.table("enrollments").select("student_id, group_id, discount").eq("center_id", cid).execute().data or []:
            disc[(e["student_id"], e["group_id"])] = float(e.get("discount") or 0)
    except Exception:
        disc = {}
    out = {}
    for e in center_enrollments(cid):
        k = (e["student_id"], e["group_id"])
        base = gfees.get(e["group_id"], 0) or 0
        out[k] = max(0.0, base - disc.get(k, 0.0))
    return out


def enrollment_discounts(cid: str) -> dict:
    """(student_id, group_id) -> chegirma summasi."""
    try:
        rows = supabase.table("enrollments").select("student_id, group_id, discount").eq("center_id", cid).execute().data or []
        return {(r["student_id"], r["group_id"]): float(r.get("discount") or 0) for r in rows}
    except Exception:
        return {}


def set_discount(cid: str, student_id: str, group_id: str, amount: float):
    try:
        supabase.table("enrollments").update({"discount": amount}).eq("center_id", cid).eq("student_id", student_id).eq("group_id", group_id).execute()
    except Exception:
        pass


# ---- O'quvchi ketish xavfi (ketma-ket kelmaganlar) ------------------
def absence_streaks(cid: str, threshold: int = 3) -> list:
    """Har o'quvchining oxirgi darslardagi ketma-ket 'absent' soni.
    threshold dan katta/teng bo'lganlarni qaytaradi: [{student_id, group_id, streak, last_date}]."""
    try:
        rows = (supabase.table("attendance").select("student_id, group_id, status, date")
                .eq("center_id", cid).order("date", desc=True).limit(4000).execute().data) or []
    except Exception:
        rows = []
    seq = {}
    for a in rows:  # date DESC tartibida
        key = (a["student_id"], a["group_id"])
        seq.setdefault(key, []).append(a)
    out = []
    for key, items in seq.items():
        streak = 0
        last_date = None
        for a in items:  # eng yangidan eskiga
            if a["status"] == "absent":
                streak += 1
                if last_date is None:
                    last_date = a["date"]
            else:
                break
        if streak >= threshold:
            out.append({"student_id": key[0], "group_id": key[1], "streak": streak, "last_date": last_date})
    out.sort(key=lambda x: x["streak"], reverse=True)
    return out


# ---- HISOBLAR (kassa: naqd / karta / click / payme) -----------------
def accounts(cid: str, only_active: bool = True) -> list:
    """Markaz hisoblari (sort bo'yicha)."""
    try:
        q = supabase.table("accounts").select("*").eq("center_id", cid)
        rows = q.execute().data or []
    except Exception:
        rows = []
    if only_active:
        rows = [a for a in rows if a.get("is_active", True) is not False]
    rows.sort(key=lambda a: (a.get("sort", 0), a.get("created_at", "")))
    return rows


def account_balances(cid: str) -> dict:
    """{account_id: balans} = boshlang'ich + kirim(to'lovlar) − chiqim(xarajat/maosh/obuna)."""
    accs = accounts(cid, only_active=False)
    bal = {a["id"]: float(a.get("opening_balance") or 0) for a in accs}

    def _add(table, sign):
        try:
            rows = supabase.table(table).select("account_id, amount").eq("center_id", cid).execute().data or []
        except Exception:
            rows = []
        for r in rows:
            aid = r.get("account_id")
            if aid in bal:
                bal[aid] += sign * float(r.get("amount") or 0)

    _add("payments", +1)          # o'quvchi to'lovlari (kirim)
    _add("expenses", -1)          # xarajatlar (chiqim)
    _add("teacher_payouts", -1)   # o'qituvchi maoshi (chiqim)
    _add("center_payments", -1)   # obuna to'lovi (chiqim)
    return bal


def account_map(cid: str) -> dict:
    return {a["id"]: a for a in accounts(cid, only_active=False)}


# ---- HISOBOT yordamchilari -----------------------------------------
def center_debtors(cid: str) -> dict:
    """{student_id: umumiy qarz} — start..joriy oy bo'yicha."""
    pf = pair_fees(cid)
    paid = paid_total_by_pair(cid)
    starts = enrollment_starts(cid)
    now = cur_ym()
    out = {}
    for (sid, gid), fee in pf.items():
        start = starts.get((sid, gid)) or now
        summ = pair_summary(start, now, fee, paid.get((sid, gid), 0.0))
        if summ["debt"] > 0:
            out[sid] = out.get(sid, 0.0) + summ["debt"]
    return out


def attendance_by_student(cid: str, start=None, end=None) -> dict:
    """{student_id: (kelgan, jami)} — sana oralig'i bo'yicha (ixtiyoriy)."""
    try:
        q = supabase.table("attendance").select("student_id, status, date").eq("center_id", cid)
        if start:
            q = q.gte("date", start)
        if end:
            q = q.lte("date", end)
        rows = q.execute().data or []
    except Exception:
        rows = []
    out = {}
    for r in rows:
        sid = r.get("student_id")
        p, t = out.get(sid, (0, 0))
        t += 1
        if r.get("status") in ("present", "late"):
            p += 1
        out[sid] = (p, t)
    return out


def birthdays_this_month(cid: str) -> list:
    """Yaqin tug'ilgan kunlar — BUGUN yoki ERTAGA. O'tib ketgani ko'rinmaydi.
    greeted = shu yili tabrik yuborilganmi."""
    from datetime import date as _date, timedelta as _td
    months = ["", "Yanvar", "Fevral", "Mart", "Aprel", "May", "Iyun",
              "Iyul", "Avgust", "Sentyabr", "Oktyabr", "Noyabr", "Dekabr"]
    today = _date.today()
    tomorrow = today + _td(days=1)
    try:
        rows = supabase.table("students").select("id, full_name, parent_phone, birth_date, active, birthday_greeted_year").eq("center_id", cid).execute().data or []
    except Exception:
        try:
            rows = supabase.table("students").select("id, full_name, parent_phone, birth_date, active").eq("center_id", cid).execute().data or []
        except Exception:
            rows = []
    out = []
    for s in rows:
        if s.get("active", True) is False:
            continue
        bd = s.get("birth_date")
        if not bd:
            continue
        try:
            d = _date.fromisoformat(str(bd)[:10])
        except Exception:
            continue
        # shu yildagi tug'ilgan kun sanasi
        try:
            this_year = d.replace(year=today.year)
        except ValueError:
            this_year = d.replace(year=today.year, day=28)  # 29-fevral chekka holati
        if this_year not in (today, tomorrow):
            continue
        label = f"{d.day}-{months[d.month]}"
        if d.year and d.year > 1900:
            label += f" {d.year}"
        out.append({
            "id": s["id"], "name": s.get("full_name", "—"), "phone": s.get("parent_phone"),
            "day": d.day, "date_label": label,
            "today": this_year == today,
            "greeted": s.get("birthday_greeted_year") == today.year,
        })
    out.sort(key=lambda x: (0 if x["today"] else 1))
    return out
