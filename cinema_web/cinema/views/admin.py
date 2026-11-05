"""Admin: UC69 (quản lý tài khoản & phân quyền) · (cấu hình tham số hệ thống)"""
from datetime import date

from flask import Blueprint, render_template, request, redirect, url_for, flash, g
from werkzeug.security import generate_password_hash

from ..db import q, q1, ex, run
from ..security import roles_required, ADMIN, EMAIL_RE, PHONE_RE, valid_password
from .. import services as sv

bp = Blueprint("admin", __name__)


@bp.route("/admin/accounts")
@roles_required(ADMIN)
def accounts():
    rows = q("SELECT u.*, r.role_code, r.role_name FROM users u JOIN roles r ON r.role_id=u.role_id ORDER BY u.user_id")
    return render_template("admin/accounts.html", rows=rows, roles=q("SELECT * FROM roles ORDER BY role_id"))


@bp.route("/admin/accounts/add", methods=["GET", "POST"])
@roles_required(ADMIN)
def account_add():
    roles = q("SELECT * FROM roles ORDER BY role_id")
    if request.method == "POST":
        f = request.form
        email, name, pw = f.get("email", "").strip().lower(), f.get("full_name", "").strip(), f.get("password", "")
        role = q1("SELECT * FROM roles WHERE role_id=%s", (f.get("role_id"),))
        phone = f.get("phone", "").strip()
        err = None
        if not (email and name and pw and role):
            err = "Vui lòng nhập đầy đủ thông tin bắt buộc"
        elif not EMAIL_RE.match(email):
            err = "Email không đúng định dạng"
        elif q1("SELECT 1 AS x FROM users WHERE email=%s", (email,)):
            err = "Tên đăng nhập/email đã tồn tại"                                      # 6a
        elif not valid_password(pw):
            err = "Mật khẩu phải có tối thiểu 8 ký tự, gồm chữ hoa và số"
        elif phone and (not PHONE_RE.match(phone) or q1("SELECT 1 AS x FROM users WHERE phone=%s", (phone,))):
            err = "Số điện thoại không hợp lệ hoặc đã tồn tại"
        if err:
            flash(err, "danger")
            return render_template("admin/account_form.html", roles=roles, f=f, u=None)
        uid = ex("INSERT INTO users (role_id, email, password_hash, full_name, phone) VALUES (%s,%s,%s,%s,%s)",
                 (role["role_id"], email, generate_password_hash(pw), name, phone or None))
        _ensure_profile(uid, role["role_code"])
        flash("Tạo tài khoản thành công", "success")
        return redirect(url_for("admin.accounts"))
    return render_template("admin/account_form.html", roles=roles, f={}, u=None)


def _ensure_profile(uid, role_code):
    """Khách -> hồ sơ thành viên; nhân viên/quản lý -> hồ sơ nhân viên (Quản lý rạp bổ sung chi tiết ở mục Nhân viên)."""
    if role_code == "CUSTOMER":
        if not q1("SELECT 1 AS x FROM customers WHERE user_id=%s", (uid,)):
            ex("INSERT INTO customers (user_id, tier_id) VALUES (%s, (SELECT tier_id FROM membership_tiers ORDER BY min_points LIMIT 1))", (uid,))
    elif role_code in ("TICKET_STAFF", "WAREHOUSE_STAFF", "MANAGER"):
        if not q1("SELECT 1 AS x FROM employees WHERE user_id=%s", (uid,)):
            pos = {"TICKET_STAFF": "Nhân viên bán vé", "WAREHOUSE_STAFF": "Nhân viên kho", "MANAGER": "Quản lý rạp"}[role_code]
            ex("INSERT INTO employees (user_id, position, employment_type, hourly_wage, hire_date) VALUES (%s,%s,'PART_TIME',0,%s)",
               (uid, pos, date.today()))


@bp.route("/admin/accounts/<int:uid>/edit", methods=["GET", "POST"])
@roles_required(ADMIN)
def account_edit(uid):
    u = q1("SELECT u.*, r.role_code FROM users u JOIN roles r ON r.role_id=u.role_id WHERE u.user_id=%s", (uid,))
    if not u:
        return render_template("error.html", code=404, msg="Không tìm thấy tài khoản"), 404
    roles = q("SELECT * FROM roles ORDER BY role_id")
    if request.method == "POST":
        f = request.form
        role = q1("SELECT * FROM roles WHERE role_id=%s", (f.get("role_id"),))
        name, pw = f.get("full_name", "").strip(), f.get("password", "")
        status = "LOCKED" if f.get("status") == "LOCKED" else "ACTIVE"
        err = None
        if not (name and role):
            err = "Vui lòng nhập đầy đủ thông tin bắt buộc"
        elif pw and not valid_password(pw):
            err = "Mật khẩu phải có tối thiểu 8 ký tự, gồm chữ hoa và số"
        elif uid == g.user["user_id"] and (status == "LOCKED" or role["role_code"] != ADMIN):
            err = "Không thể tự khóa hoặc hạ quyền chính mình"
        if err:
            flash(err, "danger")
            return render_template("admin/account_form.html", roles=roles, f=f, u=u)
        run("UPDATE users SET full_name=%s, role_id=%s, status=%s WHERE user_id=%s", (name, role["role_id"], status, uid))
        if pw:
            run("UPDATE users SET password_hash=%s WHERE user_id=%s", (generate_password_hash(pw), uid))
        _ensure_profile(uid, role["role_code"])
        flash("Cập nhật tài khoản thành công", "success")
        return redirect(url_for("admin.accounts"))
    return render_template("admin/account_form.html", roles=roles, f=u, u=u)


@bp.route("/admin/accounts/<int:uid>/delete", methods=["POST"])
@roles_required(ADMIN)
def account_delete(uid):
    if uid == g.user["user_id"]:
        raise sv.AppError("Không thể xóa chính mình")
    try:
        # xóa hồ sơ phụ nếu chưa phát sinh dữ liệu, rồi xóa tài khoản
        run("DELETE FROM notifications WHERE user_id=%s", (uid,))
        run("DELETE FROM customers WHERE user_id=%s AND NOT EXISTS (SELECT 1 FROM bookings b WHERE b.customer_id=customers.customer_id)", (uid,))
        run("DELETE FROM users WHERE user_id=%s", (uid,))
        flash("Đã xóa tài khoản", "success")
    except Exception:
        from .. import db as dbm
        dbm.rollback()
        run("UPDATE users SET status='LOCKED' WHERE user_id=%s", (uid,))
        flash("Tài khoản đã có dữ liệu liên quan nên được khóa thay vì xóa hẳn", "warning")
    return redirect(url_for("admin.accounts"))


# Cấu hình tham số hệ thống
@bp.route("/admin/settings", methods=["GET", "POST"])
@roles_required(ADMIN)
def settings():
    if request.method == "POST":
        f = request.form
        errs, updates, tiers = [], [], []
        for s in q("SELECT * FROM system_settings"):
            key = f"s_{s['setting_key']}"
            if key in f:
                v = f[key].strip()
                try:
                    n = float(v)
                except ValueError:
                    errs.append(f"{s['setting_key']}: không phải số")
                    continue
                if n < 0 or (s["setting_key"].endswith("PERCENT") and n > 100):
                    errs.append(f"{s['setting_key']}: giá trị không hợp lệ")
                    continue
                updates.append((v, g.user["user_id"], s["setting_key"]))
        for t in q("SELECT * FROM membership_tiers"):
            key = f"t_{t['tier_id']}"
            if key in f:
                try:
                    n = float(f[key])
                except ValueError:
                    n = -1
                if not 0 <= n <= 100:
                    errs.append(f"% giảm hạng {t['tier_name']} phải từ 0 đến 100")                       # 4a
                else:
                    tiers.append((n, t["tier_id"]))
        if errs:
            flash("Tham số không hợp lệ: " + "; ".join(errs), "danger")
            return redirect(url_for("admin.settings"))
        for u in updates:
            run("UPDATE system_settings SET setting_value=%s, updated_by=%s WHERE setting_key=%s", u)
        for t in tiers:
            run("UPDATE membership_tiers SET discount_percent=%s WHERE tier_id=%s", t)
        flash("Đã lưu cấu hình, áp dụng ngay không cần sửa mã nguồn", "success")
        return redirect(url_for("admin.settings"))
    return render_template("admin/settings.html", settings=q("SELECT * FROM system_settings ORDER BY setting_key"),
                           tiers=q("SELECT * FROM membership_tiers ORDER BY min_points"),
                           types=q("SELECT * FROM ticket_types ORDER BY type_name"),
                           promos=q("SELECT * FROM promotions WHERE day_of_week IS NOT NULL OR promo_type='SPECIAL_DAY' ORDER BY promotion_id"))
