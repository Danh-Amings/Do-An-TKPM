"""QLBV: UC35-UC40 · UC20 (sơ đồ ghế) · UC22/UC37 (giữ chỗ) · UC38 (đơn giá) · UC39 (QR) · UC36 (bán tại quầy) · QLTV: UC47-UC48"""
from datetime import datetime, timedelta

from flask import (Blueprint, render_template, request, redirect, url_for, flash, jsonify, session, g, abort)

from .. import db as dbm
from ..db import q, q1, ex, run, in_clause
from ..security import (roles_required, login_required, is_role, CUSTOMER, TICKET_STAFF, MANAGER, ADMIN, PHONE_RE)
from .. import services as sv
from .. import payments
from .. import booking_states

bp = Blueprint("booking", __name__)
ONLINE_METHODS = payments.online_methods()


# tiện ích
def eff_status(b):
    """Trạng thái hiển thị ở tab 'Vé của tôi' (UC48) - lấy từ lớp trạng thái (mẫu State)."""
    return booking_states.display_state(b["status"], sv.to_dt(b["start_time"]), sv.to_dt(b["end_time"]), sv.now()).code


def ticket_types_for(room_type):
    return q("SELECT * FROM ticket_types WHERE is_active=1 AND (room_type IS NULL OR room_type=%s) ORDER BY base_price", (room_type,))


def get_cart():
    return session.get("cart")


def cart_required():
    c = get_cart()
    if not c or not c.get("seats"):
        raise sv.AppError("Giỏ đặt vé trống, vui lòng chọn suất chiếu và ghế")
    return c


def booking_or_404(bid, allow_staff=True):
    b = q1("SELECT b.*, s.start_time, s.end_time, s.room_id, m.title, m.movie_id, m.poster_url, r.room_name, r.room_type, ci.name AS cinema, "
           "cu.user_id AS cust_user, u.full_name AS cust_name, u.phone AS cust_phone FROM bookings b JOIN showtimes s ON s.showtime_id=b.showtime_id "
           "JOIN movies m ON m.movie_id=s.movie_id JOIN rooms r ON r.room_id=s.room_id JOIN cinemas ci ON ci.cinema_id=r.cinema_id "
           "JOIN customers cu ON cu.customer_id=b.customer_id JOIN users u ON u.user_id=cu.user_id WHERE b.booking_id=%s", (bid,))
    if not b:
        abort(404)
    own = g.customer and b["customer_id"] == g.customer["customer_id"]
    if not own and not (allow_staff and is_role(TICKET_STAFF, MANAGER)):
        abort(403)
    return b


def load_booking_parts(b):
    tickets = q("SELECT t.*, s.row_label, s.seat_number, tt.type_name FROM tickets t JOIN seats s ON s.seat_id=t.seat_id "
                "JOIN ticket_types tt ON tt.ticket_type_id=t.ticket_type_id WHERE t.booking_id=%s ORDER BY t.ticket_id", (b["booking_id"],))
    items = q("SELECT bi.*, p.product_name FROM booking_items bi JOIN fb_products p ON p.product_id=bi.product_id WHERE bi.booking_id=%s",
              (b["booking_id"],))
    pay = q1("SELECT * FROM payments WHERE booking_id=%s ORDER BY payment_id DESC LIMIT 1", (b["booking_id"],))
    return tickets, items, pay


def change_allowed(b):
    """UC40: chỉ đổi/hủy trước giờ chiếu tối thiểu theo chính sách."""
    mins = sv.setting("CANCEL_BEFORE_MIN", 120)
    return sv.now() <= sv.to_dt(b["start_time"]) - timedelta(minutes=mins), mins


#  Sơ đồ ghế
@bp.route("/showtimes/<int:sid>/seats")
def seat_picker(sid):
    sv.sweep()
    s = q1("SELECT s.*, m.title, m.duration_min, m.age_rating, r.room_name, r.room_type, c.name AS cinema FROM showtimes s "
           "JOIN movies m ON m.movie_id=s.movie_id JOIN rooms r ON r.room_id=s.room_id JOIN cinemas c ON c.cinema_id=r.cinema_id "
           "WHERE s.showtime_id=%s", (sid,))
    if not s:
        abort(404)
    mode = "view"
    exchange_for = request.args.get("exchange", type=int)
    if exchange_for:
        mode = "exchange"
    elif g.user["role_code"] == CUSTOMER and request.args.get("view") != "1":
        mode = "online"
    elif g.user["role_code"] == TICKET_STAFF and request.args.get("view") != "1":
        c = get_cart()
        if not c or c.get("mode") != "counter" or not c.get("customer_id"):
            flash("Hãy nhập thông tin khách hàng trước khi chọn ghế", "info")
            return redirect(url_for("booking.counter_start", showtime=sid))
        mode = "counter"
    if mode != "view":
        try:
            sv.check_showtime_open(sid)
        except sv.AppError as e:
            flash(str(e), "danger")
            return redirect(url_for("movies.movie_detail", movie_id=s["movie_id"]))
    types = ticket_types_for(s["room_type"])
    start = sv.to_dt(s["start_time"])
    prices = {t["ticket_type_id"]: sv.ticket_base_price(t, start) for t in types}
    pct, _, label = sv.best_discount(g.customer if mode in ("online", "exchange") else
                                     (q1("SELECT * FROM customers WHERE customer_id=%s", (get_cart()["customer_id"],)) if mode == "counter" else None), start)
    return render_template("booking/seat_picker.html", s=s, mode=mode, types=types, prices=prices, pct=pct, label=label,
                           max_seats=sv.setting("MAX_SEATS_PER_BOOKING", 10), hold_seconds=sv.setting("HOLD_SECONDS", 300),
                           exchange_for=exchange_for)


@bp.route("/api/showtimes/<int:sid>/seats")
@login_required
def api_seats(sid):
    sv.sweep()
    return jsonify(seats=sv.seat_map(sid, g.user["user_id"]))


@bp.route("/api/cart/hold", methods=["POST"])
@login_required
def api_hold():
    data = request.get_json(silent=True) or {}
    sid = int(data.get("showtime_id", 0))
    seats = data.get("seats", [])
    mode = data.get("mode", "online")
    try:
        if mode == "online" and g.user["role_code"] != CUSTOMER:
            raise sv.AppError("Chỉ khách hàng mới đặt vé trực tuyến")
        if mode == "counter" and g.user["role_code"] not in (TICKET_STAFF, ADMIN):
            raise sv.AppError("Chỉ nhân viên bán vé mới bán vé tại quầy")
        sv.sweep()
        s = sv.check_showtime_open(sid)
        ids = [int(x["seat_id"]) for x in seats]
        until = sv.hold_seats(g.user["user_id"], sid, ids)
        lines = []
        if mode == "exchange":
            old = q1("SELECT COUNT(*) AS n FROM tickets WHERE booking_id=%s AND status='VALID'", (data.get("booking_id"),))["n"]
            if old != len(ids):
                raise sv.AppError(f"Cần chọn đúng {old} ghế để đổi")
            session["cart"] = dict(mode="exchange", showtime_id=sid, seats=[dict(seat_id=i) for i in ids], booking_id=int(data["booking_id"]))
        else:
            allowed = {t["ticket_type_id"] for t in ticket_types_for(s["room_type"])}
            for x in seats:
                if int(x["ticket_type_id"]) not in allowed:
                    raise sv.AppError("Loại vé không áp dụng cho phòng chiếu này")
                lines.append(dict(seat_id=int(x["seat_id"]), ticket_type_id=int(x["ticket_type_id"])))
            old = get_cart() or {}
            session["cart"] = dict(mode=mode, showtime_id=sid, seats=lines, combos=old.get("combos", {}) if old.get("showtime_id") == sid else {},
                                   customer_id=old.get("customer_id") if mode == "counter" else None)
        if mode == "exchange":
            nxt = url_for("booking.exchange_confirm", bid=data["booking_id"])
        else:
            nxt = url_for("booking.combo_step")
        return jsonify(ok=True, next=nxt, held_until=until.isoformat())
    except sv.AppError as e:
        dbm.rollback()
        return jsonify(ok=False, message=str(e)), 409


# Combo F&B
@bp.route("/booking/combo", methods=["GET", "POST"])
def combo_step():
    c = cart_required()
    if c["mode"] not in ("online", "counter"):
        abort(400)
    products = q("SELECT * FROM fb_products WHERE is_active=1 AND category<>'INGREDIENT' ORDER BY is_combo DESC, category, product_name")
    for p in products:
        p["available"] = sv.product_available(p["product_id"])
    if request.method == "POST":
        combos = {}
        for p in products:
            n = request.form.get(f"qty_{p['product_id']}", "0")
            if n.isdigit() and int(n) > 0:
                if int(n) > p["available"]:
                    flash(f"Món \"{p['product_name']}\" chỉ còn {p['available']}, vui lòng chọn lại hoặc chọn món khác", "danger")   # 3a
                    return redirect(url_for("booking.combo_step"))
                combos[str(p["product_id"])] = int(n)
        c["combos"] = combos
        session["cart"] = c
        return redirect(url_for("booking.checkout"))
    return render_template("booking/combo.html", products=products, cart=c, show_id=c["showtime_id"])


# Thanh toán
def _cart_pricing():
    c = cart_required()
    s = sv.check_showtime_open(c["showtime_id"])
    customer = (q1("SELECT * FROM customers WHERE customer_id=%s", (c["customer_id"],)) if c["mode"] == "counter" else g.customer)
    if not customer:
        raise sv.AppError("Không xác định được khách hàng")
    lines, ticket_total, discount, promo_id, label = sv.price_lines(s, customer, [(x["seat_id"], x["ticket_type_id"]) for x in c["seats"]])
    combos = {int(k): v for k, v in c.get("combos", {}).items()}
    cl, combo_total = sv.combo_lines(combos)
    return c, s, customer, lines, ticket_total, discount, label, cl, combo_total


@bp.route("/booking/checkout", methods=["GET", "POST"])
def checkout():
    sv.sweep()
    c, s, customer, lines, ticket_total, discount, label, cl, combo_total = _cart_pricing()
    ids = [x["seat_id"] for x in c["seats"]]
    try:
        sv.verify_holds(g.user["user_id"], c["showtime_id"], ids)
    except sv.AppError as e:
        session.pop("cart", None)
        flash(str(e), "danger")
        return redirect(url_for("booking.seat_picker", sid=c["showtime_id"]))
    held = q1("SELECT MIN(held_until) AS t FROM showtime_seats WHERE showtime_id=%s AND held_by=%s AND status='HELD'",
              (c["showtime_id"], g.user["user_id"]))
    total = ticket_total + combo_total
    if request.method == "POST":
        if c["mode"] == "counter":
            bid, _ = sv.create_booking(customer=customer, showtime_id=c["showtime_id"], lines=[(l["seat_id"], l["ticket_type_id"]) for l in lines],
                                       combos={p["product_id"]: n for p, n in cl}, channel="COUNTER", user_id=g.user["user_id"],
                                       sold_by=g.employee["employee_id"] if g.employee else None, method="CASH")
            sv.finalize_paid(bid, "CASH", emp_id=g.employee["employee_id"] if g.employee else None)
            session.pop("cart", None)
            flash("Đã thu tiền và xuất vé cho khách hàng", "success")
            return redirect(url_for("booking.booking_print", bid=bid))
        method = request.form.get("method")
        strategy = payments.find_payment(method)
        if strategy is None:
            flash("Vui lòng chọn phương thức thanh toán", "danger")
            return redirect(url_for("booking.checkout"))
        bid, _ = sv.create_booking(customer=customer, showtime_id=c["showtime_id"], lines=[(l["seat_id"], l["ticket_type_id"]) for l in lines],
                                   combos={p["product_id"]: n for p, n in cl}, channel="ONLINE", user_id=g.user["user_id"], method=method)
        session.pop("cart", None)
        if strategy.pay_at_counter:                                                    # 8a
            flash("Đặt vé thành công, vui lòng thanh toán tại quầy trước giờ chiếu", "success")
            return redirect(url_for("booking.booking_detail", bid=bid))
        return redirect(url_for("booking.pay", bid=bid))
    return render_template("booking/checkout.html", c=c, s=s, customer=customer, lines=lines, cl=cl, ticket_total=ticket_total,
                           combo_total=combo_total, discount=discount, label=label, total=total, held_until=sv.to_dt(held["t"]) if held and held["t"] else None,
                           methods=ONLINE_METHODS, now=sv.now())


@bp.route("/booking/cancel-cart", methods=["POST"])
def cancel_cart():
    sv.release_user_holds(g.user["user_id"])
    session.pop("cart", None)
    flash("Đã hủy lựa chọn và nhả ghế", "info")
    return redirect(url_for("main.home"))


# Cổng thanh toán (giả lập)
@bp.route("/booking/<int:bid>/pay", methods=["GET", "POST"])
def pay(bid):
    sv.sweep()
    b = booking_or_404(bid, allow_staff=False)
    pay_row = q1("SELECT * FROM payments WHERE booking_id=%s ORDER BY payment_id DESC LIMIT 1", (bid,))
    if b["status"] == "CANCELLED":
        flash("Đơn hàng đã bị hủy do hết thời gian giữ ghế. Vui lòng đặt lại.", "danger")
        return redirect(url_for("booking.booking_detail", bid=bid))
    if b["payment_status"] == "PAID":
        return redirect(url_for("booking.booking_detail", bid=bid))
    if request.method == "POST":
        res = request.form.get("result")
        if res == "ok":
            sv.finalize_paid(bid, pay_row["method"], txn_ref=f"SIM{bid:06d}")
            flash("Thanh toán thành công. Vé điện tử đã được xuất.", "success")
            return redirect(url_for("booking.booking_detail", bid=bid))
        if res == "cancel":
            sv.cancel_booking_internal(bid, "Khách hủy thanh toán", refund=0)
            flash("Đã hủy đơn hàng", "info")
            return redirect(url_for("booking.my_tickets"))
        run("UPDATE payments SET status='FAILED' WHERE payment_id=%s", (pay_row["payment_id"],))
        ex("INSERT INTO payments (booking_id, method, amount, status) VALUES (%s,%s,%s,'PENDING')", (bid, pay_row["method"], pay_row["amount"]))
        flash("Thanh toán thất bại. Bạn có thể thử lại hoặc hủy đơn.", "danger")       # 8a
        return redirect(url_for("booking.pay", bid=bid))
    held = q1("SELECT MIN(ss.held_until) AS t FROM tickets t JOIN showtime_seats ss ON ss.showtime_id=t.showtime_id AND ss.seat_id=t.seat_id "
              "WHERE t.booking_id=%s AND ss.status='HELD'", (bid,))
    return render_template("booking/pay.html", b=b, pay=pay_row, methods=ONLINE_METHODS,
                           held_until=sv.to_dt(held["t"]) if held and held["t"] else None, now=sv.now())


# Vé của tôi / Vé QR
@bp.route("/my-tickets")
@roles_required(CUSTOMER)
def my_tickets():
    sv.sweep()
    tab = request.args.get("tab", "UPCOMING")
    rows = q("SELECT b.*, s.start_time, s.end_time, m.title, r.room_name, ci.name AS cinema FROM bookings b JOIN showtimes s ON "
             "s.showtime_id=b.showtime_id JOIN movies m ON m.movie_id=s.movie_id JOIN rooms r ON r.room_id=s.room_id "
             "JOIN cinemas ci ON ci.cinema_id=r.cinema_id WHERE b.customer_id=%s ORDER BY b.booking_id DESC", (g.customer["customer_id"],))
    for b in rows:
        b["eff"] = eff_status(b)
    counts = {s.code: 0 for s in booking_states.ALL}
    for b in rows:
        counts[b["eff"]] += 1
    return render_template("booking/my_tickets.html", rows=[b for b in rows if b["eff"] == tab], tab=tab, counts=counts)


@bp.route("/booking/<int:bid>")
def booking_detail(bid):
    sv.sweep()
    b = booking_or_404(bid)
    tickets, items, pay_row = load_booking_parts(b)
    b["eff"] = eff_status(b)
    ok, mins = change_allowed(b)
    return render_template("booking/detail.html", b=b, tickets=tickets, items=items, pay=pay_row, change_ok=ok, mins=mins,
                           can_change=booking_states.state_of(b["eff"]).can_change)


@bp.route("/booking/<int:bid>/print")
def booking_print(bid):
    b = booking_or_404(bid)
    tickets, items, pay_row = load_booking_parts(b)
    return render_template("booking/print.html", b=b, tickets=tickets, items=items, pay=pay_row)


#  Đổi / Hủy vé
@bp.route("/booking/<int:bid>/cancel", methods=["POST"])
def booking_cancel(bid):
    b = booking_or_404(bid)
    ok, mins = change_allowed(b)
    booking_states.state_of(b["status"]).require_changeable("hủy")
    if not ok:
        flash(f"Quá thời gian cho phép: chỉ được đổi/hủy vé trước giờ chiếu tối thiểu {mins} phút", "danger")   # 2a
        return redirect(url_for("booking.booking_detail", bid=bid))
    sel = [int(x) for x in request.form.getlist("ticket_ids")]
    valid = q("SELECT * FROM tickets WHERE booking_id=%s AND status='VALID'", (bid,))
    chosen = [t for t in valid if not sel or t["ticket_id"] in sel]
    if not chosen:
        raise sv.AppError("Vui lòng chọn vé cần hủy")
    refund = 0
    if b["payment_status"] == "PAID":
        refund = int(sum(int(t["unit_price"]) for t in chosen) * sv.setting("REFUND_PERCENT", 100) / 100)
    sv.cancel_booking_internal(bid, "Khách/nhân viên hủy vé", refund=refund, tickets=[t["ticket_id"] for t in chosen])
    for t in chosen:
        ex("INSERT INTO ticket_changes (ticket_id, change_type, refund_amount, processed_by) VALUES (%s,'CANCEL',%s,%s)",
           (t["ticket_id"], int(int(t["unit_price"]) * sv.setting("REFUND_PERCENT", 100) / 100) if b["payment_status"] == "PAID" else 0,
            g.user["user_id"]))
    if refund:
        sv.revoke_points(b["customer_id"], refund, bid, f"Hoàn điểm do hủy vé {b['booking_code']}")
    sv.notify(b["cust_user"], f"Hủy vé {b['booking_code']}", f"Đã hủy {len(chosen)} vé. Hoàn tiền: {refund:,}đ".replace(",", "."))
    flash(f"Đã hủy vé. Số tiền hoàn: {refund:,}đ".replace(",", "."), "success")
    return redirect(url_for("booking.booking_detail", bid=bid))


@bp.route("/booking/<int:bid>/exchange")
def exchange_start(bid):
    b = booking_or_404(bid)
    ok, mins = change_allowed(b)
    booking_states.state_of(b["status"]).require_changeable("đổi vé")
    if not ok:
        flash(f"Quá thời gian cho phép: chỉ được đổi/hủy vé trước giờ chiếu tối thiểu {mins} phút", "danger")
        return redirect(url_for("booking.booking_detail", bid=bid))
    rows = q("SELECT s.showtime_id, s.start_time, r.room_name, c.name AS cinema, (SELECT COUNT(*) FROM showtime_seats ss WHERE "
             "ss.showtime_id=s.showtime_id AND ss.status='AVAILABLE') AS free_seats FROM showtimes s JOIN rooms r ON r.room_id=s.room_id "
             "JOIN cinemas c ON c.cinema_id=r.cinema_id WHERE s.movie_id=%s AND s.status='SCHEDULED' AND s.start_time>%s AND s.showtime_id<>%s "
             "AND r.room_type=%s ORDER BY s.start_time", (b["movie_id"], sv.now(), b["showtime_id"], b["room_type"]))
    n = q1("SELECT COUNT(*) AS n FROM tickets WHERE booking_id=%s AND status='VALID'", (bid,))["n"]
    return render_template("booking/exchange.html", b=b, rows=rows, n=n)


@bp.route("/booking/<int:bid>/exchange/confirm", methods=["GET", "POST"])
def exchange_confirm(bid):
    b = booking_or_404(bid)
    c = get_cart()
    if not c or c.get("mode") != "exchange" or c.get("booking_id") != bid:
        return redirect(url_for("booking.exchange_start", bid=bid))
    new_sid = c["showtime_id"]
    ids = sorted(x["seat_id"] for x in c["seats"])
    sv.verify_holds(g.user["user_id"], new_sid, ids)
    new_show = sv.check_showtime_open(new_sid)
    old = q("SELECT t.*, s.row_label, s.seat_number FROM tickets t JOIN seats s ON s.seat_id=t.seat_id WHERE t.booking_id=%s AND t.status='VALID' "
            "ORDER BY t.ticket_id", (bid,))
    new = q("SELECT seat_id, row_label, seat_number FROM seats WHERE seat_id IN (" + in_clause(ids) + ") ORDER BY seat_id", tuple(ids))
    if request.method == "POST":
        ok, mins = change_allowed(b)
        if not ok:
            raise sv.AppError(f"Quá thời gian cho phép: chỉ được đổi/hủy vé trước giờ chiếu tối thiểu {mins} phút")
        for t, ns in zip(old, new):
            run("UPDATE showtime_seats SET status='AVAILABLE', held_by=NULL, held_until=NULL WHERE showtime_id=%s AND seat_id=%s",
                (t["showtime_id"], t["seat_id"]))
            new_status = "SOLD"
            run("UPDATE showtime_seats SET status=%s, held_by=NULL, held_until=NULL WHERE showtime_id=%s AND seat_id=%s",
                (new_status, new_sid, ns["seat_id"]))
            run("UPDATE tickets SET showtime_id=%s, seat_id=%s WHERE ticket_id=%s", (new_sid, ns["seat_id"], t["ticket_id"]))
            ex("INSERT INTO ticket_changes (ticket_id, change_type, new_showtime_id, new_seat_id, processed_by) VALUES (%s,'EXCHANGE',%s,%s,%s)",
               (t["ticket_id"], new_sid, ns["seat_id"], g.user["user_id"]))
        run("UPDATE bookings SET showtime_id=%s WHERE booking_id=%s", (new_sid, bid))
        session.pop("cart", None)
        sv.notify(b["cust_user"], f"Đổi vé {b['booking_code']}", f"Vé đã được đổi sang suất {sv.to_dt(new_show['start_time']):%H:%M %d/%m/%Y}")
        flash("Đổi vé thành công", "success")
        return redirect(url_for("booking.booking_detail", bid=bid))
    return render_template("booking/exchange_confirm.html", b=b, old=old, new=new, new_show=new_show)


#  Bán vé tại quầy
@bp.route("/counter", methods=["GET", "POST"])
@roles_required(TICKET_STAFF)
def counter_start():
    sv.sweep()
    day0 = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    shows = q("SELECT s.showtime_id, s.start_time, m.title, r.room_name, r.room_type FROM showtimes s JOIN movies m ON m.movie_id=s.movie_id "
              "JOIN rooms r ON r.room_id=s.room_id WHERE s.status='SCHEDULED' AND s.start_time>%s AND s.start_time<%s ORDER BY s.start_time",
              (sv.now(), day0 + timedelta(days=3)))
    if request.method == "POST":
        phone, name, sid = request.form.get("phone", "").strip(), request.form.get("full_name", "").strip(), request.form.get("showtime_id")
        if not PHONE_RE.match(phone):
            flash("Số điện thoại không hợp lệ", "danger")
            return redirect(url_for("booking.counter_start"))
        if not sid:
            flash("Vui lòng chọn suất chiếu", "danger")
            return redirect(url_for("booking.counter_start"))
        u = q1("SELECT u.user_id, u.full_name, r.role_code FROM users u JOIN roles r ON r.role_id=u.role_id WHERE u.phone=%s", (phone,))
        if u and u["role_code"] != CUSTOMER:
            raise sv.AppError("Số điện thoại này thuộc tài khoản nhân viên, không thể dùng làm khách hàng")
        if not u:
            if not name:
                flash("Khách hàng mới: vui lòng nhập họ tên", "danger")
                return redirect(url_for("booking.counter_start"))
            role = q1("SELECT role_id FROM roles WHERE role_code='CUSTOMER'")
            uid = ex("INSERT INTO users (role_id, full_name, phone) VALUES (%s,%s,%s)", (role["role_id"], name, phone))
            cid = ex("INSERT INTO customers (user_id, tier_id) VALUES (%s, (SELECT tier_id FROM membership_tiers ORDER BY min_points LIMIT 1))", (uid,))
        else:
            cu = q1("SELECT customer_id FROM customers WHERE user_id=%s", (u["user_id"],))
            cid = cu["customer_id"] if cu else ex("INSERT INTO customers (user_id, tier_id) VALUES (%s, (SELECT tier_id FROM membership_tiers ORDER BY min_points LIMIT 1))", (u["user_id"],))
        session["cart"] = dict(mode="counter", customer_id=cid, showtime_id=int(sid), seats=[], combos={})
        return redirect(url_for("booking.seat_picker", sid=sid))
    return render_template("booking/counter_start.html", shows=shows, pre=request.args.get("showtime", type=int))


@bp.route("/api/customers/lookup")
@roles_required(TICKET_STAFF)
def customer_lookup():
    u = q1("SELECT u.full_name, c.total_points, t.tier_name FROM users u JOIN customers c ON c.user_id=u.user_id JOIN membership_tiers t "
           "ON t.tier_id=c.tier_id WHERE u.phone=%s", (request.args.get("phone", "").strip(),))
    return jsonify(found=bool(u), name=u["full_name"] if u else "", points=u["total_points"] if u else 0, tier=u["tier_name"] if u else "")


@bp.route("/counter/pending", methods=["GET", "POST"])
@roles_required(TICKET_STAFF)
def counter_pending():
    """Xác nhận thu tiền cho đơn đặt online chọn 'thanh toán tại quầy' (UC35 luồng thay thế 8a)."""
    sv.sweep()
    if request.method == "POST":
        bid = int(request.form["booking_id"])
        sv.finalize_paid(bid, "CASH", emp_id=g.employee["employee_id"] if g.employee else None)
        run("UPDATE bookings SET sold_by=%s WHERE booking_id=%s", (g.employee["employee_id"] if g.employee else None, bid))
        flash("Đã xác nhận thu tiền và xuất vé", "success")
        return redirect(url_for("booking.booking_print", bid=bid))
    code = request.args.get("code", "").strip()
    sql = ("SELECT b.*, m.title, s.start_time, u.full_name, u.phone FROM bookings b JOIN showtimes s ON s.showtime_id=b.showtime_id "
           "JOIN movies m ON m.movie_id=s.movie_id JOIN customers c ON c.customer_id=b.customer_id JOIN users u ON u.user_id=c.user_id "
           "JOIN payments p ON p.booking_id=b.booking_id WHERE b.status='PENDING_CONFIRM' AND p.method='CASH' AND p.status='PENDING'")
    args = []
    if code:
        sql += " AND (b.booking_code LIKE %s OR u.phone LIKE %s)"
        args += [f"%{code}%", f"%{code}%"]
    return render_template("booking/counter_pending.html", rows=q(sql + " ORDER BY s.start_time", tuple(args)), code=code)


@bp.route("/counter/lookup")
@roles_required(TICKET_STAFF)
def counter_lookup():
    """Tìm đơn theo mã/SĐT để đổi, hủy vé cho khách (UC40 - nhân viên bán vé)."""
    code = request.args.get("code", "").strip()
    rows = []
    if code:
        rows = q("SELECT b.*, m.title, s.start_time, u.full_name, u.phone FROM bookings b JOIN showtimes s ON s.showtime_id=b.showtime_id "
                 "JOIN movies m ON m.movie_id=s.movie_id JOIN customers c ON c.customer_id=b.customer_id JOIN users u ON u.user_id=c.user_id "
                 "WHERE b.booking_code LIKE %s OR u.phone LIKE %s ORDER BY b.booking_id DESC LIMIT 30", (f"%{code}%", f"%{code}%"))
    return render_template("booking/counter_lookup.html", rows=rows, code=code)


# Lịch sử giao dịch & điểm
@bp.route("/account/history")
@roles_required(CUSTOMER)
def member_history():
    cid = g.customer["customer_id"]
    bookings = q("SELECT b.*, m.title FROM bookings b JOIN showtimes s ON s.showtime_id=b.showtime_id JOIN movies m ON m.movie_id=s.movie_id "
                 "WHERE b.customer_id=%s ORDER BY b.booking_id DESC", (cid,))
    orders = q("SELECT * FROM fb_orders WHERE customer_id=%s ORDER BY fb_order_id DESC", (cid,))
    points = q("SELECT * FROM point_history WHERE customer_id=%s ORDER BY point_id DESC", (cid,))
    tier = q1("SELECT * FROM membership_tiers WHERE tier_id=%s", (g.customer["tier_id"],))
    nxt = q1("SELECT * FROM membership_tiers WHERE min_points>%s ORDER BY min_points LIMIT 1", (g.customer["total_points"],))
    return render_template("booking/history.html", bookings=bookings, orders=orders, points=points, tier=tier, nxt=nxt)
