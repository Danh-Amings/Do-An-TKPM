"""QLNV: UC49-UC55 (nhân viên, ca làm việc, chấm công, khiếu nại lương)"""
from datetime import date, datetime, timedelta

from flask import Blueprint, render_template, request, redirect, url_for, flash, g
from werkzeug.security import generate_password_hash

from ..db import q, q1, ex, run
from ..security import roles_required, employee_required, MANAGER, EMAIL_RE, PHONE_RE, valid_password
from .. import services as sv

bp = Blueprint("hr", __name__)
STAFF_ROLES = {"TICKET_STAFF": "Nhân viên bán vé / quầy", "WAREHOUSE_STAFF": "Nhân viên kho / F&B", "MANAGER": "Quản lý rạp"}
EMP_TYPES = {"FULL_TIME": "Toàn thời gian", "PART_TIME": "Bán thời gian (Part-time)"}
REG_STATUS = {"PENDING": "Chờ duyệt", "APPROVED": "Đã duyệt", "REJECTED": "Từ chối"}


# ================================================================== UC49-UC52 Quản lý nhân viên
@bp.route("/hr/employees")
@roles_required(MANAGER)
def employee_list():                                                                  # UC49
    rows = q("SELECT e.*, u.full_name, u.phone, u.email, u.status AS acc_status, r.role_name FROM employees e JOIN users u ON u.user_id=e.user_id "
             "JOIN roles r ON r.role_id=u.role_id ORDER BY e.status, u.full_name")
    return render_template("hr/employees.html", rows=rows, EMP_TYPES=EMP_TYPES)


def _emp_form():
    f = request.form
    return dict(full_name=f.get("full_name", "").strip(), phone=f.get("phone", "").strip(), position=f.get("position", "").strip(),
                role_code=f.get("role_code", "TICKET_STAFF"), email=f.get("email", "").strip().lower(), password=f.get("password", ""),
                employment_type=f.get("employment_type", "PART_TIME"), hourly_wage=f.get("hourly_wage", "0").strip() or "0",
                hire_date=f.get("hire_date") or date.today().isoformat())


@bp.route("/hr/employees/add", methods=["GET", "POST"])
@roles_required(MANAGER)
def employee_add():                                                                   # UC50
    if request.method == "POST":
        d = _emp_form()
        err = None
        if not (d["full_name"] and d["phone"] and d["position"] and d["email"] and d["password"]):
            err = "Vui lòng nhập đầy đủ thông tin bắt buộc"
        elif d["role_code"] not in STAFF_ROLES or not d["hourly_wage"].isdigit():
            err = "Vai trò hoặc mức lương không hợp lệ"
        elif not PHONE_RE.match(d["phone"]):
            err = "Số điện thoại không hợp lệ"
        elif q1("SELECT 1 AS x FROM users WHERE phone=%s", (d["phone"],)):
            err = "SĐT đã tồn tại"                                                     # 3a
        elif not EMAIL_RE.match(d["email"]) or q1("SELECT 1 AS x FROM users WHERE email=%s", (d["email"],)):
            err = "Email không hợp lệ hoặc đã được sử dụng"
        elif not valid_password(d["password"]):
            err = "Mật khẩu phải có tối thiểu 8 ký tự, gồm chữ hoa và số"
        if err:
            flash(err, "danger")
            return render_template("hr/employee_form.html", e=d, roles=STAFF_ROLES, types=EMP_TYPES, edit=False)
        role = q1("SELECT role_id FROM roles WHERE role_code=%s", (d["role_code"],))
        uid = ex("INSERT INTO users (role_id, email, password_hash, full_name, phone) VALUES (%s,%s,%s,%s,%s)",
                 (role["role_id"], d["email"], generate_password_hash(d["password"]), d["full_name"], d["phone"]))
        ex("INSERT INTO employees (user_id, position, employment_type, hourly_wage, hire_date) VALUES (%s,%s,%s,%s,%s)",
           (uid, d["position"], d["employment_type"], int(d["hourly_wage"]), d["hire_date"]))
        flash("Thêm nhân viên thành công", "success")
        return redirect(url_for("hr.employee_list"))
    return render_template("hr/employee_form.html", e=dict(role_code="TICKET_STAFF", employment_type="PART_TIME", hourly_wage="0"),
                           roles=STAFF_ROLES, types=EMP_TYPES, edit=False)


@bp.route("/hr/employees/<int:eid>/edit", methods=["GET", "POST"])
@roles_required(MANAGER)
def employee_edit(eid):                                                               # UC52
    e = q1("SELECT e.*, u.full_name, u.phone, u.email, r.role_code FROM employees e JOIN users u ON u.user_id=e.user_id "
           "JOIN roles r ON r.role_id=u.role_id WHERE e.employee_id=%s", (eid,))
    if not e:
        return render_template("error.html", code=404, msg="Không tìm thấy nhân viên"), 404
    if request.method == "POST":
        d = _emp_form()
        err = None
        if not (d["full_name"] and d["phone"] and d["position"]):
            err = "Vui lòng nhập đầy đủ thông tin bắt buộc"                           # 4a
        elif not PHONE_RE.match(d["phone"]):
            err = "Số điện thoại không hợp lệ"
        elif q1("SELECT 1 AS x FROM users WHERE phone=%s AND user_id<>%s", (d["phone"], e["user_id"])):
            err = "SĐT đã tồn tại"
        elif d["role_code"] not in STAFF_ROLES or not d["hourly_wage"].isdigit():
            err = "Vai trò hoặc mức lương không hợp lệ"
        if err:
            flash(err, "danger")
            return render_template("hr/employee_form.html", e=dict(d, employee_id=eid, email=e["email"]), roles=STAFF_ROLES, types=EMP_TYPES, edit=True)
        role = q1("SELECT role_id FROM roles WHERE role_code=%s", (d["role_code"],))
        run("UPDATE users SET full_name=%s, phone=%s, role_id=%s WHERE user_id=%s", (d["full_name"], d["phone"], role["role_id"], e["user_id"]))
        run("UPDATE employees SET position=%s, employment_type=%s, hourly_wage=%s WHERE employee_id=%s",
            (d["position"], d["employment_type"], int(d["hourly_wage"]), eid))
        flash("Cập nhật thông tin nhân viên thành công", "success")
        return redirect(url_for("hr.employee_list"))
    return render_template("hr/employee_form.html", e=e, roles=STAFF_ROLES, types=EMP_TYPES, edit=True)


@bp.route("/hr/employees/<int:eid>/delete", methods=["POST"])
@roles_required(MANAGER)
def employee_delete(eid):                                                             # UC51: nghỉ việc (xóa mềm để giữ lịch sử chấm công/lương)
    e = q1("SELECT * FROM employees WHERE employee_id=%s", (eid,))
    if e and e["user_id"] == g.user["user_id"]:
        raise sv.AppError("Không thể tự xóa chính mình")
    if e:
        run("UPDATE employees SET status='RESIGNED' WHERE employee_id=%s", (eid,))
        run("UPDATE users SET status='LOCKED' WHERE user_id=%s", (e["user_id"],))
        flash("Đã xóa nhân viên (nghỉ việc) và khóa tài khoản", "success")
    return redirect(url_for("hr.employee_list"))


# ================================================================== UC53 Đăng ký & duyệt ca
def approved_count(shift_id, work_date):
    return q1("SELECT COUNT(*) AS n FROM shift_registrations WHERE shift_id=%s AND work_date=%s AND status='APPROVED'", (shift_id, work_date))["n"]


@bp.route("/hr/shifts", methods=["GET", "POST"])
@employee_required
def shift_register():
    eid = g.employee["employee_id"]
    if request.method == "POST":
        sid, d = request.form.get("shift_id"), sv.to_date(request.form.get("work_date"))
        sh = q1("SELECT * FROM shifts WHERE shift_id=%s", (sid,))
        if not sh or d < date.today():
            raise sv.AppError("Ca làm việc hoặc ngày không hợp lệ")
        if q1("SELECT 1 AS x FROM shift_registrations WHERE employee_id=%s AND shift_id=%s AND work_date=%s", (eid, sid, d)):
            raise sv.AppError("Bạn đã đăng ký ca này rồi")
        if approved_count(sid, d) >= int(sh["max_staff"]):
            flash("Ca làm việc đã đủ nhân viên", "danger")                             # 6a
            return redirect(url_for("hr.shift_register"))
        ex("INSERT INTO shift_registrations (employee_id, shift_id, work_date) VALUES (%s,%s,%s)", (eid, sid, d))
        sv.notify_roles([MANAGER], "Đăng ký ca làm việc mới", f"{g.user['full_name']} đăng ký {sh['shift_name']} ngày {d:%d/%m/%Y}")
        flash("Đã đăng ký ca, vui lòng chờ Quản lý duyệt", "success")
        return redirect(url_for("hr.shift_register"))
    shifts = q("SELECT * FROM shifts ORDER BY start_time")
    days = [date.today() + timedelta(days=i) for i in range(14)]
    mine = {(r["shift_id"], sv.to_date(r["work_date"])): r["status"] for r in
            q("SELECT * FROM shift_registrations WHERE employee_id=%s AND work_date>=%s", (eid, date.today()))}
    counts = {(r["shift_id"], sv.to_date(r["work_date"])): r["n"] for r in
              q("SELECT shift_id, work_date, COUNT(*) AS n FROM shift_registrations WHERE status='APPROVED' AND work_date>=%s "
                "GROUP BY shift_id, work_date", (date.today(),))}
    return render_template("hr/shifts.html", shifts=shifts, days=days, mine=mine, counts=counts, REG_STATUS=REG_STATUS)


@bp.route("/hr/shifts/manage", methods=["GET", "POST"])
@roles_required(MANAGER)
def shift_manage():
    if request.method == "POST":
        r = q1("SELECT r.*, s.max_staff, s.shift_name FROM shift_registrations r JOIN shifts s ON s.shift_id=r.shift_id "
               "WHERE r.registration_id=%s", (request.form.get("registration_id"),))
        act = request.form.get("action")
        if r and r["status"] == "PENDING":
            if act == "approve":
                if approved_count(r["shift_id"], sv.to_date(r["work_date"])) >= int(r["max_staff"]):
                    raise sv.AppError("Ca làm việc đã đủ nhân viên")
                run("UPDATE shift_registrations SET status='APPROVED', approved_by=%s WHERE registration_id=%s",
                    (g.employee["employee_id"] if g.employee else None, r["registration_id"]))
            else:
                run("UPDATE shift_registrations SET status='REJECTED', approved_by=%s WHERE registration_id=%s",
                    (g.employee["employee_id"] if g.employee else None, r["registration_id"]))
            eu = q1("SELECT user_id FROM employees WHERE employee_id=%s", (r["employee_id"],))
            sv.notify(eu["user_id"], "Kết quả đăng ký ca", f"{r['shift_name']} ngày {sv.to_date(r['work_date']):%d/%m/%Y}: "
                      f"{'đã được duyệt' if act == 'approve' else 'bị từ chối'}")
            flash("Đã cập nhật", "success")
        return redirect(url_for("hr.shift_manage"))
    rows = q("SELECT r.*, s.shift_name, s.max_staff, u.full_name, e.employment_type, "
             "(SELECT COUNT(*) FROM shift_registrations x WHERE x.shift_id=r.shift_id AND x.work_date=r.work_date AND x.status='APPROVED') AS ok "
             "FROM shift_registrations r JOIN shifts s ON s.shift_id=r.shift_id JOIN employees e ON e.employee_id=r.employee_id "
             "JOIN users u ON u.user_id=e.user_id WHERE r.status='PENDING' ORDER BY r.work_date, "
             "CASE e.employment_type WHEN 'PART_TIME' THEN 0 ELSE 1 END, r.registered_at")           # ưu tiên Part-time
    return render_template("hr/shift_manage.html", rows=rows, EMP_TYPES=EMP_TYPES)


# ================================================================== UC54 Chấm công & đối chiếu vi phạm
def mark_incomplete_attendance():
    at = sv.now()
    rows = q("SELECT a.attendance_id, r.work_date, s.end_time, e.user_id, u.full_name FROM attendance a JOIN shift_registrations r ON "
             "r.registration_id=a.registration_id JOIN shifts s ON s.shift_id=r.shift_id JOIN employees e ON e.employee_id=r.employee_id "
             "JOIN users u ON u.user_id=e.user_id WHERE a.status='IN_PROGRESS' AND a.check_out IS NULL")
    for a in rows:
        end = datetime.combine(sv.to_date(a["work_date"]), sv.to_time(a["end_time"]))
        if end < at:
            run("UPDATE attendance SET status='INCOMPLETE' WHERE attendance_id=%s", (a["attendance_id"],))
            sv.notify_roles([MANAGER], "Quên check-out", f"{a['full_name']} chưa check-out ca ngày {sv.to_date(a['work_date']):%d/%m/%Y}")
            sv.notify(a["user_id"], "Chưa hoàn tất chấm công", "Bạn đã quên check-out ca làm việc.")


@bp.route("/hr/attendance", methods=["GET", "POST"])
@employee_required
def attendance():
    eid = g.employee["employee_id"]
    mark_incomplete_attendance()
    today = date.today()
    if request.method == "POST":
        act = request.form.get("action")
        at = sv.now()                                                                 # Server Time
        regs = q("SELECT r.*, s.start_time, s.end_time, s.shift_name FROM shift_registrations r JOIN shifts s ON s.shift_id=r.shift_id "
                 "WHERE r.employee_id=%s AND r.work_date=%s AND r.status='APPROVED' ORDER BY s.start_time", (eid, today))
        if act == "in":
            if not regs:
                flash("Bạn chưa đăng ký ca làm việc", "danger")                        # 1a
                return redirect(url_for("hr.attendance"))
            target = None
            for r in regs:
                if not q1("SELECT 1 AS x FROM attendance WHERE registration_id=%s", (r["registration_id"],)):
                    target = r
                    break
            if not target:
                raise sv.AppError("Bạn đã check-in tất cả các ca hôm nay")
            start = datetime.combine(today, sv.to_time(target["start_time"]))
            late = max(0, int((at - start).total_seconds() // 60))
            viol = late > sv.setting("LATE_THRESHOLD_MIN", 15)                          # đến muộn > 15 phút
            ex("INSERT INTO attendance (registration_id, check_in, late_minutes, is_violation) VALUES (%s,%s,%s,%s)",
               (target["registration_id"], at, late, 1 if viol else 0))
            if viol:
                sv.notify_roles([MANAGER], "Vi phạm giờ giấc", f"{g.user['full_name']} đến muộn {late} phút ({target['shift_name']})")
                flash(f"Check-in lúc {at:%H:%M}. Bạn đến muộn {late} phút (vi phạm giờ giấc).", "warning")
            else:
                flash(f"Check-in thành công lúc {at:%H:%M}", "success")
        elif act == "out":
            a = q1("SELECT a.* FROM attendance a JOIN shift_registrations r ON r.registration_id=a.registration_id WHERE r.employee_id=%s "
                   "AND a.check_out IS NULL AND a.status='IN_PROGRESS' ORDER BY a.attendance_id DESC LIMIT 1", (eid,))
            if not a:
                raise sv.AppError("Bạn chưa check-in hoặc đã check-out")
            run("UPDATE attendance SET check_out=%s, status='COMPLETED' WHERE attendance_id=%s", (at, a["attendance_id"]))
            flash(f"Check-out thành công lúc {at:%H:%M}", "success")
        return redirect(url_for("hr.attendance"))
    todays = q("SELECT r.*, s.shift_name, s.start_time, s.end_time, a.check_in, a.check_out, a.late_minutes, a.is_violation, a.status AS att_status "
               "FROM shift_registrations r JOIN shifts s ON s.shift_id=r.shift_id LEFT JOIN attendance a ON a.registration_id=r.registration_id "
               "WHERE r.employee_id=%s AND r.work_date=%s AND r.status='APPROVED' ORDER BY s.start_time", (eid, today))
    history = q("SELECT r.work_date, s.shift_name, a.* FROM attendance a JOIN shift_registrations r ON r.registration_id=a.registration_id "
                "JOIN shifts s ON s.shift_id=r.shift_id WHERE r.employee_id=%s ORDER BY a.attendance_id DESC LIMIT 30", (eid,))
    return render_template("hr/attendance.html", todays=todays, history=history, now=sv.now())


# ================================================================== Phiếu lương & UC55 Khiếu nại lương
@bp.route("/hr/payslips", methods=["GET", "POST"])
@employee_required
def payslips():
    if request.method == "POST":
        if g.user["role_code"] not in (MANAGER, "ADMIN"):
            raise sv.AppError("Bạn không có quyền tạo phiếu lương")
        month, year = int(request.form["month"]), int(request.form["year"])
        n = 0
        for e in q("SELECT * FROM employees WHERE status='WORKING'"):
            rows = q("SELECT a.check_in, a.check_out, a.is_violation FROM attendance a JOIN shift_registrations r ON r.registration_id=a.registration_id "
                     "WHERE r.employee_id=%s AND a.status='COMPLETED' AND r.work_date>=%s AND r.work_date<%s",
                     (e["employee_id"], date(year, month, 1), date(year + (month == 12), month % 12 + 1, 1)))
            hours = sum((sv.to_dt(r["check_out"]) - sv.to_dt(r["check_in"])).total_seconds() / 3600 for r in rows)
            gross = int(hours * int(e["hourly_wage"]))
            ded = sum(1 for r in rows if r["is_violation"]) * sv.setting("VIOLATION_FINE", 0)
            net = max(0, gross - ded)
            old = q1("SELECT payslip_id FROM payslips WHERE employee_id=%s AND pay_month=%s AND pay_year=%s", (e["employee_id"], month, year))
            if old:
                run("UPDATE payslips SET total_hours=%s, gross_amount=%s, deduction=%s, net_amount=%s WHERE payslip_id=%s",
                    (round(hours, 2), gross, ded, net, old["payslip_id"]))
            else:
                ex("INSERT INTO payslips (employee_id, pay_month, pay_year, total_hours, gross_amount, deduction, net_amount) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                   (e["employee_id"], month, year, round(hours, 2), gross, ded, net))
            n += 1
        flash(f"Đã tính phiếu lương tháng {month}/{year} cho {n} nhân viên", "success")
        return redirect(url_for("hr.payslips"))
    is_mgr = g.user["role_code"] in (MANAGER, "ADMIN")
    sql = ("SELECT p.*, u.full_name FROM payslips p JOIN employees e ON e.employee_id=p.employee_id JOIN users u ON u.user_id=e.user_id")
    rows = q(sql + (" ORDER BY p.pay_year DESC, p.pay_month DESC, u.full_name" if is_mgr else
                    " WHERE p.employee_id=%s ORDER BY p.pay_year DESC, p.pay_month DESC"), () if is_mgr else (g.employee["employee_id"],))
    return render_template("hr/payslips.html", rows=rows, is_mgr=is_mgr, today=date.today())


@bp.route("/hr/complaints", methods=["GET", "POST"])
@employee_required
def complaints():
    eid = g.employee["employee_id"]
    if request.method == "POST":
        content, pid = request.form.get("content", "").strip(), request.form.get("payslip_id")
        if not content or not pid:
            flash("Vui lòng chọn phiếu lương và nhập nội dung khiếu nại", "danger")
        elif not q1("SELECT 1 AS x FROM payslips WHERE payslip_id=%s AND employee_id=%s", (pid, eid)):
            raise sv.AppError("Phiếu lương không hợp lệ")
        else:
            ex("INSERT INTO salary_complaints (payslip_id, employee_id, content) VALUES (%s,%s,%s)", (pid, eid, content))
            sv.notify_roles([MANAGER], "Khiếu nại lương mới", f"{g.user['full_name']} gửi khiếu nại lương")
            flash("Đã gửi khiếu nại đến Quản lý", "success")
        return redirect(url_for("hr.complaints"))
    slips = q("SELECT * FROM payslips WHERE employee_id=%s ORDER BY pay_year DESC, pay_month DESC", (eid,))
    rows = q("SELECT c.*, p.pay_month, p.pay_year FROM salary_complaints c JOIN payslips p ON p.payslip_id=c.payslip_id "
             "WHERE c.employee_id=%s ORDER BY c.complaint_id DESC", (eid,))
    return render_template("hr/complaints.html", slips=slips, rows=rows)


@bp.route("/hr/complaints/manage", methods=["GET", "POST"])
@roles_required(MANAGER)
def complaints_manage():
    if request.method == "POST":
        c = q1("SELECT c.*, e.user_id FROM salary_complaints c JOIN employees e ON e.employee_id=c.employee_id WHERE c.complaint_id=%s",
               (request.form.get("complaint_id"),))
        resp = request.form.get("response", "").strip()
        if not c or not resp:
            flash("Vui lòng nhập nội dung phản hồi", "danger")
        else:
            run("UPDATE salary_complaints SET status='RESPONDED', response=%s, responded_by=%s, responded_at=%s WHERE complaint_id=%s",
                (resp, g.employee["employee_id"] if g.employee else None, sv.now(), c["complaint_id"]))
            sv.notify(c["user_id"], "Phản hồi khiếu nại lương", resp)
            flash("Đã phản hồi khiếu nại", "success")
        return redirect(url_for("hr.complaints_manage"))
    rows = q("SELECT c.*, p.pay_month, p.pay_year, p.net_amount, u.full_name FROM salary_complaints c JOIN payslips p ON p.payslip_id=c.payslip_id "
             "JOIN employees e ON e.employee_id=c.employee_id JOIN users u ON u.user_id=e.user_id ORDER BY c.status, c.complaint_id DESC")
    return render_template("hr/complaints_manage.html", rows=rows)
