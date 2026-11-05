import os
import threading
import time as _time
from datetime import datetime, timedelta, date

import secrets
from flask import Flask, g, session, redirect, url_for, request, render_template, abort
from markupsafe import Markup

from .config import Config
from . import db as dbm
from .db import q, q1, run
from . import services as sv
from . import observers
from . import booking_states

ROLE_LABEL = {"CUSTOMER": "Khách hàng", "TICKET_STAFF": "Nhân viên bán vé", "WAREHOUSE_STAFF": "Nhân viên kho",
              "MANAGER": "Quản lý rạp", "ADMIN": "Admin hệ thống"}
BOOKING_STATUS = booking_states.LABELS      # nhãn lấy từ các lớp trạng thái (mẫu State)
SEAT_LABEL = {"AVAILABLE": "Trống", "HELD": "Đang giữ", "SOLD": "Đã bán"}


def run_daily_jobs():
    """Job 00:00 hằng ngày: cảnh báo kho (UC43) + đánh dấu quên check-out (UC54 3a) + đóng suất đã chiếu."""
    from .views.hr import mark_incomplete_attendance
    n = sv.expiry_scan()
    mark_incomplete_attendance()
    run("UPDATE showtimes SET status='FINISHED' WHERE status='SCHEDULED' AND end_time<%s", (sv.now(),))
    return n


def _scheduler(app):
    def loop():
        while True:
            n = datetime.now()
            nxt = (n + timedelta(days=1)).replace(hour=0, minute=0, second=5, microsecond=0)
            _time.sleep(max(1, (nxt - n).total_seconds()))
            try:
                with app.app_context():
                    run_daily_jobs()
                    dbm.commit()
                    dbm.close_db()
            except Exception as e:
                print("[JOB-ERROR]", e)
    threading.Thread(target=loop, daemon=True).start()


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    #  CSRF (chống giả mạo form)
    def csrf_token():
        if "_csrf" not in session:
            session["_csrf"] = secrets.token_hex(16)
        return session["_csrf"]

    app.jinja_env.globals["csrf_token"] = csrf_token
    app.jinja_env.globals["csrf_input"] = lambda: Markup(f'<input type="hidden" name="_csrf" value="{csrf_token()}">')

    @app.before_request
    def csrf_protect():
        if request.method == "POST" and app.config.get("CSRF_ENABLED", True):
            sent = request.form.get("_csrf") or request.headers.get("X-CSRF-Token") or ""
            tok = session.get("_csrf", "")
            if not tok or not secrets.compare_digest(tok, sent):
                abort(400, "Phiên làm việc hết hạn, vui lòng tải lại trang và thử lại.")

    # vòng đời request
    @app.before_request
    def load_user():
        g.user = g.customer = g.employee = None
        if request.endpoint == "static":
            return None
        uid = session.get("uid")
        if uid:
            u = q1("SELECT u.*, r.role_code FROM users u JOIN roles r ON r.role_id=u.role_id WHERE u.user_id=%s", (uid,))
            if u and u["status"] == "ACTIVE":
                g.user = u
                g.customer = q1("SELECT * FROM customers WHERE user_id=%s", (uid,))
                g.employee = q1("SELECT * FROM employees WHERE user_id=%s AND status='WORKING'", (uid,))
            else:
                session.clear()
        ep = request.endpoint or ""
        if app.config["REQUIRE_LOGIN"] and not g.user and not ep.startswith("auth."):
            return redirect(url_for("auth.login", next=request.full_path if request.method == "GET" else None))
        return None

    @app.after_request
    def finish(resp):
        if resp.status_code < 500:
            dbm.commit()
        else:
            dbm.rollback()
        return resp

    app.teardown_request(dbm.close_db)

    # bộ lọc / biến cho template
    @app.template_filter("money")
    def money(v):
        try:
            return f"{int(v):,}".replace(",", ".") + " đ"
        except (TypeError, ValueError):
            return "-"

    @app.template_filter("dt")
    def fmt_dt(v):
        v = sv.to_dt(v)
        return v.strftime("%H:%M %d/%m/%Y") if v else ""

    @app.template_filter("d")
    def fmt_d(v):
        v = sv.to_date(v)
        return v.strftime("%d/%m/%Y") if v else ""

    @app.template_filter("hm")
    def fmt_hm(v):
        if v is None:
            return ""
        if isinstance(v, (datetime,)):
            return v.strftime("%H:%M")
        return sv.to_time(v).strftime("%H:%M")

    @app.template_filter("dow")
    def fmt_dow(v):
        return {1: "Thứ 2", 2: "Thứ 3", 3: "Thứ 4", 4: "Thứ 5", 5: "Thứ 6", 6: "Thứ 7", 7: "Chủ nhật"}.get(
            int(v) if v is not None else 0, "Mọi ngày")

    @app.context_processor
    def inject():
        unread = 0
        if g.get("user"):
            unread = q1("SELECT COUNT(*) AS n FROM notifications WHERE user_id=%s AND is_read=0", (g.user["user_id"],))["n"]
        def has_role(*codes):
            return bool(g.get("user")) and (g.user["role_code"] == "ADMIN" or g.user["role_code"] in codes)

        def is_role_exact(code):
            return bool(g.get("user")) and g.user["role_code"] == code

        return dict(has_role=has_role, is_role_exact=is_role_exact, ROLE_LABEL=ROLE_LABEL, BOOKING_STATUS=BOOKING_STATUS, SEAT_LABEL=SEAT_LABEL, unread=unread,
                    today=date.today(), now_dt=sv.now())

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("error.html", code=403, msg="Bạn không có quyền sử dụng chức năng này."), 403

    @app.errorhandler(400)
    def badreq(e):
        return render_template("error.html", code=400, msg=getattr(e, "description", "Yêu cầu không hợp lệ")), 400

    @app.errorhandler(404)
    def notfound(e):
        return render_template("error.html", code=404, msg="Không tìm thấy trang."), 404

    @app.errorhandler(sv.AppError)
    def apperr(e):
        from flask import flash
        flash(str(e), "danger")
        dbm.rollback()
        return redirect(request.referrer or url_for("main.home"))

    observers.register_default_observers()    # mẫu Observer: đăng ký các việc sau thanh toán

    #  blueprint
    from .views import (auth, main, movies, cinema, pricing, booking, fnb, hr, reports, admin)
    for m in (auth, main, movies, cinema, pricing, booking, fnb, hr, reports, admin):
        app.register_blueprint(m.bp)

    @app.cli.command("scan-expiry")
    def scan_cmd():
        """flask --app app scan-expiry : chạy thủ công job cảnh báo hạn dùng (UC43)"""
        print("Số cảnh báo mới:", run_daily_jobs())
        dbm.commit()

    if (app.config["ENABLE_SCHEDULER"] and not app.testing and not test_config
            and (not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true")):
        _scheduler(app)
    return app
