import re
from functools import wraps
from flask import g, redirect, url_for, request, abort, flash

CUSTOMER = "CUSTOMER"
TICKET_STAFF = "TICKET_STAFF"
WAREHOUSE_STAFF = "WAREHOUSE_STAFF"
MANAGER = "MANAGER"
ADMIN = "ADMIN"

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^(0|\+84)\d{9,10}$")


def valid_password(p: str) -> bool:
    """UC02: tối thiểu 8 ký tự, có chữ hoa và số"""
    return len(p) >= 8 and any(c.isupper() for c in p) and any(c.isdigit() for c in p)


def login_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if not g.user:
            return redirect(url_for("auth.login", next=request.full_path))
        return f(*a, **kw)
    return wrapper


def roles_required(*codes):
    """Admin có toàn quyền trên tất cả bộ phận (báo cáo mục 2.2)."""
    def deco(f):
        @wraps(f)
        def wrapper(*a, **kw):
            if not g.user:
                return redirect(url_for("auth.login", next=request.full_path))
            if g.user["role_code"] != ADMIN and g.user["role_code"] not in codes:
                abort(403)
            if codes == (CUSTOMER,) and not g.customer:      # Admin không có hồ sơ thành viên
                abort(403)
            return f(*a, **kw)
        return wrapper
    return deco


def employee_required(f):
    """Phần cá nhân của QLNV: mọi người có hồ sơ nhân viên (NV bán vé, NV kho, Quản lý)."""
    @wraps(f)
    def wrapper(*a, **kw):
        if not g.user:
            return redirect(url_for("auth.login", next=request.full_path))
        if not g.employee:
            abort(403)
        return f(*a, **kw)
    return wrapper


def is_role(*codes):
    return bool(g.user) and (g.user["role_code"] == ADMIN or g.user["role_code"] in codes)
