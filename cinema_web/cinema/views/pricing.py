"""QLLV: UC32-34 (loại vé & giá vé) · QLSK: UC65-68 (sự kiện & khuyến mãi)"""
from datetime import date

from flask import Blueprint, render_template, request, redirect, url_for, flash

from ..db import q, q1, ex, run
from ..security import roles_required, MANAGER
from .. import services as sv

bp = Blueprint("pricing", __name__)
ROOM_TYPES = ["2D", "3D", "IMAX"]
PROMO_TYPES = {"EVENT": "Sự kiện", "DISCOUNT": "Khuyến mãi", "SPECIAL_DAY": "Ngày ưu đãi (C'Day...)", "STUDENT": "Sinh viên (C'Student...)"}


def parse_price(s):
    try:
        v = int(str(s).replace(".", "").replace(",", "").strip())
    except ValueError:
        return None
    return v if v >= 0 else None


def _time_or(s, default):
    s = (s or "").strip()
    if not s:
        return default
    return s if len(s) > 5 else s + ":00"


# ================================================================== QLLV
@bp.route("/manage/ticket-types")
@roles_required(MANAGER)
def ticket_types():                                                                  # UC33
    rows = q("SELECT * FROM ticket_types ORDER BY type_name")
    rules = q("SELECT * FROM ticket_price_rules ORDER BY ticket_type_id, day_of_week, time_from")
    by = {}
    for r in rules:
        by.setdefault(r["ticket_type_id"], []).append(r)
    return render_template("pricing/ticket_types.html", rows=rows, rules=by, types=ROOM_TYPES)


@bp.route("/manage/ticket-types/add", methods=["POST"])
@roles_required(MANAGER)
def ticket_type_add():                                                               # UC32
    f = request.form
    name, price = f.get("type_name", "").strip(), parse_price(f.get("base_price", ""))
    if not name or price is None:
        flash("Vui lòng nhập tên loại vé và giá cơ bản hợp lệ", "danger")
    elif q1("SELECT 1 AS x FROM ticket_types WHERE type_name=%s", (name,)):
        flash("Tên loại vé đã tồn tại", "danger")                                     # 4a
    else:
        tid = ex("INSERT INTO ticket_types (type_name, room_type, base_price) VALUES (%s,%s,%s)",
                 (name, f.get("room_type") or None, price))
        if f.get("time_from") or f.get("time_to") or f.get("day_of_week"):            # "khung giờ áp dụng"
            ex("INSERT INTO ticket_price_rules (ticket_type_id, day_of_week, time_from, time_to, price) VALUES (%s,%s,%s,%s,%s)",
               (tid, f.get("day_of_week") or None, _time_or(f.get("time_from"), "00:00:00"), _time_or(f.get("time_to"), "23:59:59"), price))
        flash("Thêm loại vé thành công", "success")
    return redirect(url_for("pricing.ticket_types"))


@bp.route("/manage/ticket-types/<int:tid>/edit", methods=["GET", "POST"])
@roles_required(MANAGER)
def ticket_type_edit(tid):                                                           # UC34
    t = q1("SELECT * FROM ticket_types WHERE ticket_type_id=%s", (tid,))
    if not t:
        return render_template("error.html", code=404, msg="Không tìm thấy loại vé"), 404
    if request.method == "POST":
        f = request.form
        price = parse_price(f.get("base_price", ""))
        if price is None:
            flash("Giá âm hoặc không hợp lệ", "danger")                               # 5a
            return redirect(url_for("pricing.ticket_type_edit", tid=tid))
        name = f.get("type_name", "").strip()
        if not name:
            flash("Vui lòng nhập tên loại vé", "danger")
            return redirect(url_for("pricing.ticket_type_edit", tid=tid))
        if q1("SELECT 1 AS x FROM ticket_types WHERE type_name=%s AND ticket_type_id<>%s", (name, tid)):
            flash("Tên loại vé đã tồn tại", "danger")
            return redirect(url_for("pricing.ticket_type_edit", tid=tid))
        # cập nhật giá của từng quy tắc khung giờ
        for r in q("SELECT rule_id FROM ticket_price_rules WHERE ticket_type_id=%s", (tid,)):
            p = parse_price(f.get(f"rule_price_{r['rule_id']}", ""))
            if p is None:
                flash("Giá âm hoặc không hợp lệ", "danger")
                return redirect(url_for("pricing.ticket_type_edit", tid=tid))
            if f.get(f"rule_del_{r['rule_id']}"):
                run("DELETE FROM ticket_price_rules WHERE rule_id=%s", (r["rule_id"],))
            else:
                run("UPDATE ticket_price_rules SET price=%s WHERE rule_id=%s", (p, r["rule_id"]))
        if f.get("new_price"):
            np_ = parse_price(f["new_price"])
            if np_ is None:
                flash("Giá âm hoặc không hợp lệ", "danger")
                return redirect(url_for("pricing.ticket_type_edit", tid=tid))
            ex("INSERT INTO ticket_price_rules (ticket_type_id, day_of_week, time_from, time_to, price) VALUES (%s,%s,%s,%s,%s)",
               (tid, f.get("new_dow") or None, _time_or(f.get("new_from"), "00:00:00"), _time_or(f.get("new_to"), "23:59:59"), np_))
        run("UPDATE ticket_types SET type_name=%s, room_type=%s, base_price=%s, is_active=%s WHERE ticket_type_id=%s",
            (name, f.get("room_type") or None, price, 1 if f.get("is_active") else 0, tid))
        flash("Cập nhật giá vé thành công", "success")
        return redirect(url_for("pricing.ticket_types"))
    rules = q("SELECT * FROM ticket_price_rules WHERE ticket_type_id=%s ORDER BY day_of_week, time_from", (tid,))
    return render_template("pricing/ticket_type_edit.html", t=t, rules=rules, types=ROOM_TYPES)


# ================================================================== QLSK
def _promo_form():
    f = request.form
    d = dict(name=f.get("name", "").strip(), promo_type=f.get("promo_type", "DISCOUNT"), description=f.get("description", "").strip(),
             condition_text=f.get("condition_text", "").strip(), day_of_week=f.get("day_of_week") or None,
             min_tier_id=f.get("min_tier_id") or None, start_date=f.get("start_date"), end_date=f.get("end_date"),
             is_active=1 if f.get("is_active", "1") == "1" else 0)
    try:
        d["discount_percent"] = float(f.get("discount_percent", "0") or 0)
    except ValueError:
        d["discount_percent"] = -1
    return d


def _promo_validate(d):
    if not (d["name"] and d["start_date"] and d["end_date"]):
        return "Vui lòng nhập tên, thời gian bắt đầu và kết thúc"
    if sv.to_date(d["end_date"]) < sv.to_date(d["start_date"]):
        return "Ngày kết thúc không được trước ngày bắt đầu"                         # 3a
    if not 0 <= d["discount_percent"] <= 100:
        return "Mức giảm phải từ 0 đến 100 (%)"
    return None


@bp.route("/manage/promotions")
@roles_required(MANAGER)
def promo_list():                                                                    # UC65
    rows = q("SELECT p.*, t.tier_name FROM promotions p LEFT JOIN membership_tiers t ON t.tier_id=p.min_tier_id "
             "ORDER BY p.end_date DESC, p.promotion_id DESC")
    return render_template("pricing/promos.html", rows=rows, PROMO_TYPES=PROMO_TYPES, today=date.today())


@bp.route("/manage/promotions/add", methods=["GET", "POST"])
@roles_required(MANAGER)
def promo_add():                                                                     # UC66
    if request.method == "POST":
        d = _promo_form()
        err = _promo_validate(d)
        if err:
            flash(err, "danger")
            return render_template("pricing/promo_form.html", p=d, PROMO_TYPES=PROMO_TYPES, tiers=q("SELECT * FROM membership_tiers"))
        ex("INSERT INTO promotions (name, promo_type, description, discount_percent, condition_text, day_of_week, min_tier_id, "
           "start_date, end_date, is_active) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
           (d["name"], d["promo_type"], d["description"], d["discount_percent"], d["condition_text"], d["day_of_week"],
            d["min_tier_id"], d["start_date"], d["end_date"], d["is_active"]))
        flash("Thêm sự kiện / khuyến mãi thành công", "success")
        return redirect(url_for("pricing.promo_list"))
    return render_template("pricing/promo_form.html", p=dict(promo_type="DISCOUNT", is_active=1, discount_percent=0),
                           PROMO_TYPES=PROMO_TYPES, tiers=q("SELECT * FROM membership_tiers"))


@bp.route("/manage/promotions/<int:pid>/edit", methods=["GET", "POST"])
@roles_required(MANAGER)
def promo_edit(pid):                                                                 # UC67
    p = q1("SELECT * FROM promotions WHERE promotion_id=%s", (pid,))
    if not p:
        return render_template("error.html", code=404, msg="Không tìm thấy"), 404
    if request.method == "POST":
        d = _promo_form()
        err = _promo_validate(d)
        if err:
            flash(err, "danger")
            return render_template("pricing/promo_form.html", p=dict(d, promotion_id=pid), PROMO_TYPES=PROMO_TYPES,
                                   tiers=q("SELECT * FROM membership_tiers"))
        run("UPDATE promotions SET name=%s, promo_type=%s, description=%s, discount_percent=%s, condition_text=%s, day_of_week=%s, "
            "min_tier_id=%s, start_date=%s, end_date=%s, is_active=%s WHERE promotion_id=%s",
            (d["name"], d["promo_type"], d["description"], d["discount_percent"], d["condition_text"], d["day_of_week"],
             d["min_tier_id"], d["start_date"], d["end_date"], d["is_active"], pid))
        flash("Cập nhật sự kiện / khuyến mãi thành công", "success")
        return redirect(url_for("pricing.promo_list"))
    return render_template("pricing/promo_form.html", p=p, PROMO_TYPES=PROMO_TYPES, tiers=q("SELECT * FROM membership_tiers"))


@bp.route("/manage/promotions/<int:pid>/delete", methods=["POST"])
@roles_required(MANAGER)
def promo_delete(pid):                                                               # UC68
    p = q1("SELECT * FROM promotions WHERE promotion_id=%s", (pid,))
    if not p:
        return redirect(url_for("pricing.promo_list"))
    if sv.to_date(p["end_date"]) >= date.today():
        flash("Chỉ được xóa sự kiện / khuyến mãi đã kết thúc", "danger")
    elif q1("SELECT 1 AS x FROM bookings WHERE promotion_id=%s", (pid,)):
        flash("Khuyến mãi đã được áp dụng cho đơn hàng nên không thể xóa (đã tự động tắt hiển thị).", "warning")
        run("UPDATE promotions SET is_active=0 WHERE promotion_id=%s", (pid,))
    else:
        run("DELETE FROM promotions WHERE promotion_id=%s", (pid,))
        flash("Đã xóa sự kiện / khuyến mãi", "success")
    return redirect(url_for("pricing.promo_list"))
