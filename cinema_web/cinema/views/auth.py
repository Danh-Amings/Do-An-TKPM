"""Đăng nhập ·  Đăng ký · Khôi phục mật khẩu ·  Đổi mật khẩu ·  Cập nhật thông tin cá nhân"""
import os
import random
import secrets
from datetime import timedelta

from flask import (Blueprint, render_template, request, redirect, url_for, flash, session, g, current_app)
from werkzeug.security import generate_password_hash, check_password_hash

from ..db import q, q1, ex, run
from ..security import EMAIL_RE, PHONE_RE, valid_password, login_required, ADMIN, MANAGER, TICKET_STAFF, WAREHOUSE_STAFF
from .. import services as sv

bp = Blueprint("auth", __name__)

MSG_PW_RULE = "Mật khẩu phải có tối thiểu 8 ký tự, gồm chữ hoa và số"


def home_for(role):
    return {"CUSTOMER": "main.home", "TICKET_STAFF": "main.home", "WAREHOUSE_STAFF": "main.home",
            "MANAGER": "main.home", "ADMIN": "main.home"}.get(role, "main.home")


# UC01
@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("main.home"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        pw = request.form.get("password", "")
        if not email or not pw:
            flash("Vui lòng nhập đầy đủ thông tin đăng nhập", "danger")           # 3a
            return render_template("auth/login.html", email=email)
        u = q1("SELECT u.*, r.role_code FROM users u JOIN roles r ON r.role_id=u.role_id WHERE u.email=%s", (email,))
        if not u or not u["password_hash"] or not check_password_hash(u["password_hash"], pw):
            flash("Sai tài khoản hoặc mật khẩu", "danger")                         # 5a
            return render_template("auth/login.html", email=email)
        if u["status"] == "LOCKED":
            flash("Tài khoản đã bị khóa, vui lòng liên hệ quản trị viên", "danger")  # 5b
            return render_template("auth/login.html", email=email)
        session.clear()
        session["uid"] = u["user_id"]
        flash("Đăng nhập thành công", "success")
        nxt = request.args.get("next") or request.form.get("next")
        if nxt and nxt.startswith("/") and not nxt.startswith("//"):
            return redirect(nxt)
        return redirect(url_for(home_for(u["role_code"])))
    return render_template("auth/login.html", email="")


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


# OTP dùng chung 
def issue_otp(email, purpose):
    code = f"{random.randint(0, 999999):06d}"
    run("UPDATE otp_codes SET is_used=1 WHERE email=%s AND purpose=%s AND is_used=0", (email, purpose))
    ttl = sv.setting("OTP_SECONDS", 180)
    ex("INSERT INTO otp_codes (email, purpose, otp_hash, expires_at) VALUES (%s,%s,%s,%s)",
       (email, purpose, generate_password_hash(code), sv.now() + timedelta(seconds=ttl)))
    sv.send_mail(email, "Mã OTP xác thực", f"Mã OTP của bạn là {code}. Có hiệu lực {ttl // 60} phút.")
    if current_app.config["DEV_SHOW_OTP"]:
        flash(f"[CHẾ ĐỘ DEV] Mã OTP: {code}", "info")


def check_otp(email, purpose, code):
    row = q1("SELECT * FROM otp_codes WHERE email=%s AND purpose=%s AND is_used=0 ORDER BY otp_id DESC LIMIT 1",
             (email, purpose))
    if not row:
        return "expired"
    if sv.to_dt(row["expires_at"]) < sv.now():
        return "expired"
    if not code or not check_password_hash(row["otp_hash"], code):
        return "invalid"
    run("UPDATE otp_codes SET is_used=1 WHERE otp_id=%s", (row["otp_id"],))
    return "ok"


# Đăng ký
@bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        f = request.form
        name, email = f.get("full_name", "").strip(), f.get("email", "").strip().lower()
        pw, pw2 = f.get("password", ""), f.get("password2", "")
        err = None
        if not (name and email and pw and pw2):
            err = "Vui lòng nhập đầy đủ thông tin"
        elif not EMAIL_RE.match(email):
            err = "Email không đúng định dạng"
        elif q1("SELECT 1 AS x FROM users WHERE email=%s", (email,)):
            err = "Email đã được sử dụng"                                           # 4a
        elif not valid_password(pw):
            err = MSG_PW_RULE                                                       # 4b
        elif pw != pw2:
            err = "Mật khẩu không trùng khớp"                                       # 4c
        if err:
            flash(err, "danger")
            return render_template("auth/register.html", f=f)
        session["reg"] = dict(full_name=name, email=email, pw=generate_password_hash(pw))
        issue_otp(email, "REGISTER")
        return redirect(url_for("auth.register_verify"))
    return render_template("auth/register.html", f={})


@bp.route("/register/verify", methods=["GET", "POST"])
def register_verify():
    reg = session.get("reg")
    if not reg:
        return redirect(url_for("auth.register"))
    if request.method == "POST":
        if request.form.get("resend"):                                              # 6b: Gửi lại mã
            issue_otp(reg["email"], "REGISTER")
            return redirect(url_for("auth.register_verify"))
        code = "".join(request.form.getlist("d")) or request.form.get("otp", "")
        res = check_otp(reg["email"], "REGISTER", code.strip())
        if res == "invalid":
            flash("OTP không chính xác", "danger")                                  # 6a
        elif res == "expired":
            flash("Mã OTP đã hết hạn", "danger")                                    # 6b
        else:
            if q1("SELECT 1 AS x FROM users WHERE email=%s", (reg["email"],)):
                flash("Email đã được sử dụng", "danger")
                return redirect(url_for("auth.register"))
            role = q1("SELECT role_id FROM roles WHERE role_code='CUSTOMER'")
            uid = ex("INSERT INTO users (role_id, email, password_hash, full_name) VALUES (%s,%s,%s,%s)",
                     (role["role_id"], reg["email"], reg["pw"], reg["full_name"]))
            ex("INSERT INTO customers (user_id, tier_id) VALUES (%s, (SELECT tier_id FROM membership_tiers ORDER BY min_points LIMIT 1))", (uid,))
            session.pop("reg", None)
            flash("Đăng ký thành công", "success")
            return redirect(url_for("auth.login"))
    return render_template("auth/otp.html", title="Xác thực email", email=reg["email"], action=url_for("auth.register_verify"))


# Khôi phục mật khẩu
@bp.route("/forgot", methods=["GET", "POST"])
def forgot():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        if not q1("SELECT 1 AS x FROM users WHERE email=%s AND password_hash IS NOT NULL", (email,)):
            flash("Email không tồn tại trong hệ thống", "danger")                   # 2a
            return render_template("auth/forgot.html", email=email)
        session["reset_email"] = email
        session.pop("reset_ok", None)
        issue_otp(email, "RESET_PASSWORD")
        return redirect(url_for("auth.forgot_verify"))
    return render_template("auth/forgot.html", email="")


@bp.route("/forgot/verify", methods=["GET", "POST"])
def forgot_verify():
    email = session.get("reset_email")
    if not email:
        return redirect(url_for("auth.forgot"))
    if request.method == "POST":
        if request.form.get("resend"):
            issue_otp(email, "RESET_PASSWORD")
            return redirect(url_for("auth.forgot_verify"))
        code = "".join(request.form.getlist("d")) or request.form.get("otp", "")
        res = check_otp(email, "RESET_PASSWORD", code.strip())
        if res == "invalid":
            flash("OTP không chính xác", "danger")                                  # 3a
        elif res == "expired":
            flash("OTP đã hết hạn", "danger")
        else:
            session["reset_ok"] = True
            return redirect(url_for("auth.reset_password"))
    return render_template("auth/otp.html", title="Khôi phục mật khẩu", email=email, action=url_for("auth.forgot_verify"))


@bp.route("/forgot/reset", methods=["GET", "POST"])
def reset_password():
    email = session.get("reset_email")
    if not email or not session.get("reset_ok"):
        return redirect(url_for("auth.forgot"))
    if request.method == "POST":
        pw, pw2 = request.form.get("password", ""), request.form.get("password2", "")
        if not valid_password(pw):
            flash(MSG_PW_RULE, "danger")                                            # 5a
        elif pw != pw2:
            flash("Mật khẩu không trùng khớp", "danger")
        else:
            run("UPDATE users SET password_hash=%s WHERE email=%s", (generate_password_hash(pw), email))
            session.pop("reset_email", None)
            session.pop("reset_ok", None)
            flash("Đặt lại mật khẩu thành công", "success")
            return redirect(url_for("auth.login"))
    return render_template("auth/reset.html")


#  Đổi mật khẩu
@bp.route("/account/password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        cur, pw, pw2 = (request.form.get(k, "") for k in ("current", "password", "password2"))
        if not g.user["password_hash"] or not check_password_hash(g.user["password_hash"], cur):
            flash("Mật khẩu hiện tại không chính xác", "danger")                    # 4a
        elif not valid_password(pw):
            flash(MSG_PW_RULE, "danger")                                            # 4b
        elif pw != pw2:
            flash("Mật khẩu không trùng khớp", "danger")
        else:
            run("UPDATE users SET password_hash=%s WHERE user_id=%s", (generate_password_hash(pw), g.user["user_id"]))
            flash("Đổi mật khẩu thành công", "success")
            return redirect(url_for("auth.change_password"))
    return render_template("auth/password.html")


#  Hồ sơ cá nhân
ALLOWED_IMG = {"png", "jpg", "jpeg", "gif", "webp"}


def save_upload(file, subdir, prefix):
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_IMG:
        raise sv.AppError("Chỉ chấp nhận ảnh png, jpg, jpeg, gif, webp")
    folder = os.path.join(current_app.config["UPLOAD_FOLDER"], subdir)
    os.makedirs(folder, exist_ok=True)
    name = f"{prefix}_{secrets.token_hex(4)}.{ext}"
    file.save(os.path.join(folder, name))
    return f"/static/uploads/{subdir}/{name}"


@bp.route("/account", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        f = request.form
        name, phone = f.get("full_name", "").strip(), f.get("phone", "").strip()
        birth, gender = f.get("birth_date") or None, f.get("gender") or None
        if not name:
            flash("Vui lòng nhập họ tên", "danger")
        elif phone and not PHONE_RE.match(phone):
            flash("Số điện thoại không hợp lệ", "danger")                           # 5a
        elif phone and q1("SELECT 1 AS x FROM users WHERE phone=%s AND user_id<>%s", (phone, g.user["user_id"])):
            flash("Số điện thoại đã được sử dụng", "danger")
        else:
            avatar = g.user["avatar_url"]
            file = request.files.get("avatar")
            if file and file.filename:
                data = file.read()
                file.seek(0)
                if len(data) > current_app.config["AVATAR_MAX_BYTES"]:
                    flash("Ảnh vượt quá dung lượng cho phép", "danger")             # 5b
                    return render_template("auth/profile.html")
                avatar = save_upload(file, "avatars", f"u{g.user['user_id']}")
            run("UPDATE users SET full_name=%s, phone=%s, birth_date=%s, gender=%s, avatar_url=%s WHERE user_id=%s",
                (name, phone or None, birth, gender, avatar, g.user["user_id"]))
            flash("Cập nhật thông tin thành công", "success")
            return redirect(url_for("auth.profile"))
    return render_template("auth/profile.html")


#Thông báo
@bp.route("/notifications")
@login_required
def notifications():
    rows = q("SELECT * FROM notifications WHERE user_id=%s ORDER BY notification_id DESC LIMIT 100", (g.user["user_id"],))
    run("UPDATE notifications SET is_read=1 WHERE user_id=%s", (g.user["user_id"],))
    return render_template("auth/notifications.html", rows=rows)
