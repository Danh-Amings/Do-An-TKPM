"""Nghiệp vụ dùng chung: giá vé, giữ ghế, thanh toán, kho FIFO, điểm thưởng, thông báo.
Chỉ dùng SQL chuẩn + tham số thời gian từ Python (không dùng NOW(), DATE_ADD...) để chạy ổn định.
"""
import random
import secrets
from datetime import datetime, timedelta, date, time

from .db import q, q1, ex, run, in_clause
from .mail import get_email_sender
from .discounts import best_discount as _best_discount
from . import payments
from .events import booking_paid, BookingPaid
from . import booking_states


class AppError(Exception):
    """Lỗi nghiệp vụ: message hiển thị thẳng cho người dùng."""


class SeatTaken(AppError):
    pass


class StockError(AppError):
    pass


# ---------------------------------------------------------------- thời gian
def now():
    return datetime.now().replace(microsecond=0)


def to_dt(v):
    if v is None or isinstance(v, datetime):
        return v
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day)
    return datetime.fromisoformat(str(v).replace(" ", "T"))


def to_date(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def to_time(v):
    """MySQL trả TIME dạng timedelta; chuẩn hóa về datetime.time"""
    if isinstance(v, time):
        return v
    if isinstance(v, timedelta):
        s = int(v.total_seconds())
        return time(s // 3600 % 24, s // 60 % 60, s % 60)
    parts = str(v).split(":")
    return time(int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0)


# Tham số hệ thống (UC70)
def setting(key, default=0):
    row = q1("SELECT setting_value FROM system_settings WHERE setting_key=%s", (key,))
    if not row:
        return default
    try:
        return type(default)(row["setting_value"]) if not isinstance(default, str) else row["setting_value"]
    except (TypeError, ValueError):
        return default


#  Thông báo / email
def notify(user_id, title, content=""):
    ex("INSERT INTO notifications (user_id, title, content) VALUES (%s,%s,%s)", (user_id, title, content))


def notify_roles(role_codes, title, content=""):
    rows = q(
        "SELECT u.user_id FROM users u JOIN roles r ON r.role_id=u.role_id "
        "WHERE r.role_code IN (" + in_clause(role_codes) + ") AND u.status='ACTIVE'", tuple(role_codes))
    for r in rows:
        notify(r["user_id"], title, content)


def send_mail(to, subject, body):
    """Giữ nguyên tên hàm cũ để các view không phải sửa; việc gửi do EmailSender (Adapter) đảm nhiệm."""
    get_email_sender().send(to, subject, body)


#  Thành viên / điểm (UC45, UC46)
def refresh_tier(customer_id):
    c = q1("SELECT total_points FROM customers WHERE customer_id=%s", (customer_id,))
    t = q1("SELECT tier_id FROM membership_tiers WHERE min_points<=%s ORDER BY min_points DESC LIMIT 1",
           (c["total_points"],))
    if t:
        run("UPDATE customers SET tier_id=%s WHERE customer_id=%s", (t["tier_id"], customer_id))


def add_points(customer_id, amount_paid, booking_id=None, reason="Tích điểm giao dịch"):
    """UC45: Điểm thưởng = Tổng tiền thanh toán ÷ 10.000"""
    divisor = setting("POINT_DIVISOR", 10000) or 10000
    pts = int(amount_paid) // divisor
    if pts <= 0:
        return 0
    ex("INSERT INTO point_history (customer_id, booking_id, points, reason) VALUES (%s,%s,%s,%s)",
       (customer_id, booking_id, pts, reason))
    run("UPDATE customers SET total_points=total_points+%s WHERE customer_id=%s", (pts, customer_id))
    refresh_tier(customer_id)
    return pts


def revoke_points(customer_id, amount, booking_id, reason):
    divisor = setting("POINT_DIVISOR", 10000) or 10000
    pts = int(amount) // divisor
    if pts <= 0:
        return
    cur = q1("SELECT total_points FROM customers WHERE customer_id=%s", (customer_id,))["total_points"]
    pts = min(pts, cur)
    if pts <= 0:
        return
    ex("INSERT INTO point_history (customer_id, booking_id, points, reason) VALUES (%s,%s,%s,%s)",
       (customer_id, booking_id, -pts, reason))
    run("UPDATE customers SET total_points=total_points-%s WHERE customer_id=%s", (pts, customer_id))
    refresh_tier(customer_id)


# Giá vé (UC38, UC46)
def ticket_base_price(tt, start_dt):
    """Giá vé theo loại vé + khung giờ/ngày trong tuần (UC34). Quy tắc cụ thể hơn thắng."""
    rules = q("SELECT * FROM ticket_price_rules WHERE ticket_type_id=%s", (tt["ticket_type_id"],))
    dow, t = start_dt.isoweekday(), start_dt.time()
    best, best_score = None, -1
    for r in rules:
        if r["day_of_week"] is not None and int(r["day_of_week"]) != dow:
            continue
        if not (to_time(r["time_from"]) <= t <= to_time(r["time_to"])):
            continue
        score = (2 if r["day_of_week"] is not None else 0) + (1 if (to_time(r["time_from"]) != time(0, 0)
                                                                   or to_time(r["time_to"]) != time(23, 59, 59)) else 0)
        if score > best_score:
            best, best_score = r, score
    return int(best["price"]) if best else int(tt["base_price"])


def best_discount(customer, start_dt):
    """KM áp dụng = mức cao nhất trong các chiến lược giảm giá (xem discounts.py - mẫu Strategy).
    Không cộng dồn để khớp công thức Đơn giá = Giá vé - (KM x Giá vé). Trả về (phần trăm, promo_id, nhãn)."""
    return _best_discount(customer, start_dt)


def price_lines(showtime, customer, lines):
    """lines = [(seat_id, ticket_type_id)] -> (list dòng, tổng vé, tổng giảm, promo_id, nhãn KM)"""
    start = to_dt(showtime["start_time"])
    pct, promo_id, label = best_discount(customer, start)
    out, total, base_total = [], 0, 0
    for seat_id, tt_id in lines:
        seat = q1("SELECT s.*, st.surcharge, st.type_name FROM seats s JOIN seat_types st "
                  "ON st.seat_type_id=s.seat_type_id WHERE s.seat_id=%s", (seat_id,))
        tt = q1("SELECT * FROM ticket_types WHERE ticket_type_id=%s AND is_active=1", (tt_id,))
        if not seat or not tt:
            raise AppError("Thông tin ghế hoặc loại vé không hợp lệ")
        base = ticket_base_price(tt, start) + int(seat["surcharge"])           # Giá vé
        unit = int(round(base - (pct / 100.0) * base))                        # Đơn giá = Giá vé - (KM x Giá vé)
        out.append(dict(seat_id=seat_id, ticket_type_id=tt_id, seat=f"{seat['row_label']}{seat['seat_number']}",
                        seat_type=seat["type_name"], type_name=tt["type_name"], base=base, promo=pct, unit=unit))
        total += unit
        base_total += base
    return out, total, base_total - total, promo_id, (label if pct else "")


# Ghế / giữ chỗ (UC20-22, UC37)
def sweep(at=None):
    """Dọn dẹp theo thời gian: ghế giữ quá hạn -> Trống; đơn chưa thanh toán bị mất ghế -> Hủy; đơn tiền mặt quá giờ chiếu -> Hủy."""
    at = at or now()
    run("UPDATE showtime_seats SET status='AVAILABLE', held_by=NULL, held_until=NULL "
        "WHERE status='HELD' AND held_until<%s", (at,))
    pend = q("SELECT b.booking_id, p.method FROM bookings b JOIN payments p ON p.booking_id=b.booking_id "
             "WHERE b.status='PENDING_CONFIRM' AND b.payment_status='UNPAID' AND p.status='PENDING'")
    for b in pend:
        tks = q("SELECT t.ticket_id, t.showtime_id, t.seat_id, ss.status FROM tickets t JOIN showtime_seats ss "
                "ON ss.showtime_id=t.showtime_id AND ss.seat_id=t.seat_id "
                "WHERE t.booking_id=%s AND t.status='VALID'", (b["booking_id"],))
        st = q1("SELECT s.start_time FROM bookings b JOIN showtimes s ON s.showtime_id=b.showtime_id "
                "WHERE b.booking_id=%s", (b["booking_id"],))
        reason = payments.get_payment(b["method"]).expiry_reason(
            [t["status"] for t in tks], to_dt(st["start_time"]) if st else None, at)
        if reason:
            cancel_booking_internal(b["booking_id"], reason, refund=0)


def seat_map(showtime_id, user_id=None):
    at = now()
    rows = q("SELECT ss.seat_id, ss.status, ss.held_by, ss.held_until, s.row_label, s.seat_number, s.is_active, "
             "st.type_name, st.surcharge FROM showtime_seats ss JOIN seats s ON s.seat_id=ss.seat_id "
             "JOIN seat_types st ON st.seat_type_id=s.seat_type_id WHERE ss.showtime_id=%s "
             "ORDER BY s.row_label, s.seat_number", (showtime_id,))
    out = []
    for r in rows:
        status = r["status"]
        mine = False
        if status == "HELD":
            if r["held_until"] is not None and to_dt(r["held_until"]) < at:
                status = "AVAILABLE"
            elif r["held_by"] == user_id:
                mine = True
        if not r["is_active"]:
            status = "BROKEN"
        out.append(dict(seat_id=r["seat_id"], row=r["row_label"], num=r["seat_number"], status=status,
                        mine=mine, type=r["type_name"], surcharge=int(r["surcharge"])))
    return out


def release_user_holds(user_id, showtime_id=None, keep=()):
    sql = "UPDATE showtime_seats SET status='AVAILABLE', held_by=NULL, held_until=NULL WHERE held_by=%s AND status='HELD'"
    args = [user_id]
    if showtime_id:
        sql += " AND showtime_id=%s"
        args.append(showtime_id)
    if keep:
        sql += " AND seat_id NOT IN (" + in_clause(keep) + ")"
        args += list(keep)
    run(sql, tuple(args))


def check_showtime_open(showtime_id):
    s = q1("SELECT s.*, m.title, m.status AS movie_status, r.status AS room_status, r.room_name, r.room_type "
           "FROM showtimes s JOIN movies m ON m.movie_id=s.movie_id JOIN rooms r ON r.room_id=s.room_id "
           "WHERE s.showtime_id=%s", (showtime_id,))
    if not s or s["status"] != "SCHEDULED":
        raise AppError("Suất chiếu không tồn tại hoặc đã bị hủy")
    if to_dt(s["start_time"]) <= now():
        raise AppError("Suất chiếu đã bắt đầu, không thể đặt vé")
    return s


def hold_seats(user_id, showtime_id, seat_ids):
    """UC37: giữ ghế tối đa 5 phút. Dùng SELECT ... FOR UPDATE để không bán trùng khi nhiều người thao tác cùng lúc."""
    check_showtime_open(showtime_id)
    max_seats = setting("MAX_SEATS_PER_BOOKING", 10)
    seat_ids = sorted(set(int(x) for x in seat_ids))
    if not seat_ids:
        raise AppError("Vui lòng chọn ít nhất 1 ghế")
    if len(seat_ids) > max_seats:
        raise AppError(f"Chỉ được chọn tối đa {max_seats} ghế cho mỗi đơn hàng")
    at = now()
    # nhả ghế đang giữ trước đó của chính người này (suất khác, hoặc ghế không còn được chọn trong suất này)
    run("UPDATE showtime_seats SET status='AVAILABLE', held_by=NULL, held_until=NULL "
        "WHERE held_by=%s AND status='HELD' AND showtime_id<>%s", (user_id, showtime_id))
    release_user_holds(user_id, showtime_id, keep=seat_ids)
    rows = q("SELECT ss.seat_id, ss.status, ss.held_by, ss.held_until, s.is_active FROM showtime_seats ss "
             "JOIN seats s ON s.seat_id=ss.seat_id WHERE ss.showtime_id=%s AND ss.seat_id IN (" + in_clause(seat_ids) +
             ") ORDER BY ss.seat_id FOR UPDATE", (showtime_id, *seat_ids))
    if len(rows) != len(seat_ids):
        raise AppError("Có ghế không thuộc suất chiếu này")
    for r in rows:
        free = r["is_active"] and (
            r["status"] == "AVAILABLE"
            or (r["status"] == "HELD" and (r["held_by"] == user_id or to_dt(r["held_until"]) < at)))
        if not free:
            raise SeatTaken("Ghế đã bị người khác chọn, vui lòng chọn lại")
    hold_s = setting("HOLD_SECONDS", 300)
    until = at + timedelta(seconds=hold_s)
    run("UPDATE showtime_seats SET status='HELD', held_by=%s, held_until=%s WHERE showtime_id=%s AND seat_id IN ("
        + in_clause(seat_ids) + ")", (user_id, until, showtime_id, *seat_ids))
    return until


def verify_holds(user_id, showtime_id, seat_ids):
    """Kiểm tra người dùng còn đang giữ đủ ghế (chưa hết 5 phút)."""
    at = now()
    rows = q("SELECT seat_id FROM showtime_seats WHERE showtime_id=%s AND status='HELD' AND held_by=%s AND held_until>=%s "
             "AND seat_id IN (" + in_clause(seat_ids) + ") FOR UPDATE", (showtime_id, user_id, at, *seat_ids))
    if len(rows) != len(seat_ids):
        raise AppError("Đã hết thời gian giữ ghế (5 phút). Vui lòng chọn lại ghế")


# Kho theo lô (UC41-UC44)
def product_available(product_id, today=None):
    """Số lượng bán được = tổng tồn các lô còn hạn; combo = min theo thành phần."""
    today = today or date.today()
    comps = q("SELECT component_id, quantity FROM combo_components WHERE combo_id=%s", (product_id,))
    if comps:
        return min(product_available(c["component_id"], today) // int(c["quantity"]) for c in comps)
    r = q1("SELECT COALESCE(SUM(qty_remaining),0) AS n FROM inventory_batches WHERE product_id=%s AND expiry_date>=%s",
           (product_id, today))
    return int(r["n"])


def fifo_deduct(product_id, qty, booking_id=None, fb_order_id=None, emp_id=None, today=None):
    """UC44: trừ kho FIFO - ưu tiên lô nhập trước, rồi hạn gần hết trước. Combo được tách thành thành phần."""
    today = today or date.today()
    comps = q("SELECT component_id, quantity FROM combo_components WHERE combo_id=%s", (product_id,))
    if comps:
        for c in comps:
            fifo_deduct(c["component_id"], qty * int(c["quantity"]), booking_id, fb_order_id, emp_id, today)
        return
    need = qty
    batches = q("SELECT batch_id, qty_remaining FROM inventory_batches WHERE product_id=%s AND qty_remaining>0 "
                "AND expiry_date>=%s ORDER BY import_date, expiry_date, batch_id FOR UPDATE", (product_id, today))
    for b in batches:
        if need <= 0:
            break
        take = min(need, int(b["qty_remaining"]))
        run("UPDATE inventory_batches SET qty_remaining=qty_remaining-%s WHERE batch_id=%s", (take, b["batch_id"]))
        ex("INSERT INTO stock_movements (batch_id, movement_type, quantity, booking_id, fb_order_id, created_by) "
           "VALUES (%s,'OUT_SALE',%s,%s,%s,%s)", (b["batch_id"], take, booking_id, fb_order_id, emp_id))
        need -= take
    if need > 0:
        name = q1("SELECT product_name FROM fb_products WHERE product_id=%s", (product_id,))["product_name"]
        raise StockError(f"Món \"{name}\" đã hết hàng")


def expiry_scan(today=None):
    """UC43: HSD <= 7 ngày -> cận hạn; HSD < hôm nay -> hết hạn. Tạo cảnh báo + gửi thông báo."""
    today = today or date.today()
    near_days = setting("NEAR_EXPIRY_DAYS", 7)
    limit = today + timedelta(days=near_days)
    batches = q("SELECT b.batch_id, b.batch_code, b.expiry_date, p.product_name FROM inventory_batches b "
                "JOIN fb_products p ON p.product_id=b.product_id WHERE b.qty_remaining>0 AND b.expiry_date<=%s", (limit,))
    created = []
    for b in batches:
        kind = "EXPIRED" if to_date(b["expiry_date"]) < today else "NEAR_EXPIRY"
        if q1("SELECT alert_id FROM stock_alerts WHERE batch_id=%s AND alert_type=%s AND alert_date=%s",
              (b["batch_id"], kind, today)):
            continue
        ex("INSERT INTO stock_alerts (batch_id, alert_type, alert_date) VALUES (%s,%s,%s)", (b["batch_id"], kind, today))
        created.append((b, kind))
    if created:
        lines = "\n".join(f"- {b['product_name']} (lô {b['batch_code']}, HSD {to_date(b['expiry_date'])}): "
                          f"{'HẾT HẠN' if k == 'EXPIRED' else 'cận hạn'}" for b, k in created)
        notify_roles(["WAREHOUSE_STAFF", "MANAGER"], f"Cảnh báo kho ngày {today}", lines)
    return len(created)


# Dặt vé / thanh toán (UC35-UC40)
def new_code(prefix, table, col):
    for _ in range(20):
        code = f"{prefix}{datetime.now():%y%m%d}{random.randint(0, 9999):04d}"
        if not q1(f"SELECT 1 AS x FROM {table} WHERE {col}=%s", (code,)):
            return code
    return f"{prefix}{secrets.token_hex(4).upper()}"


def combo_lines(combos):
    """combos = {product_id: qty} -> [(product, qty)] + kiểm tra còn hàng (UC62 3a)."""
    out, total = [], 0
    for pid, qty in combos.items():
        qty = int(qty)
        if qty <= 0:
            continue
        p = q1("SELECT * FROM fb_products WHERE product_id=%s AND is_active=1", (pid,))
        if not p:
            raise AppError("Sản phẩm không tồn tại")
        if product_available(int(pid)) < qty:
            raise StockError(f"Món \"{p['product_name']}\" đã hết hàng, vui lòng chọn món khác")
        out.append((p, qty))
        total += int(p["price"]) * qty
    return out, total


def create_booking(*, customer, showtime_id, lines, combos, channel, user_id, sold_by=None, method=None):
    """Tạo đơn + vé (chưa có QR). Gọi sau khi đã giữ ghế. method=None: tạo & thanh toán ngay (quầy)."""
    s = check_showtime_open(showtime_id)
    verify_holds(user_id, showtime_id, [l[0] for l in lines])
    tl, ticket_total, discount, promo_id, _ = price_lines(s, customer, lines)
    cl, combo_total = combo_lines(combos)
    total = ticket_total + combo_total
    code = new_code("BK", "bookings", "booking_code")
    bid = ex("INSERT INTO bookings (booking_code, customer_id, showtime_id, sold_by, channel, promotion_id, ticket_total, "
             "combo_total, discount_amount, total_amount, status, payment_status) "
             "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'PENDING_CONFIRM','UNPAID')",
             (code, customer["customer_id"], showtime_id, sold_by, channel, promo_id, ticket_total, combo_total,
              discount, total))
    for l in tl:
        ex("INSERT INTO tickets (booking_id, showtime_id, seat_id, ticket_type_id, base_price, promo_percent, unit_price) "
           "VALUES (%s,%s,%s,%s,%s,%s,%s)", (bid, showtime_id, l["seat_id"], l["ticket_type_id"], l["base"], l["promo"], l["unit"]))
    for p, qty in cl:
        ex("INSERT INTO booking_items (booking_id, product_id, quantity, unit_price) VALUES (%s,%s,%s,%s)",
           (bid, p["product_id"], qty, p["price"]))
    if method:
        ex("INSERT INTO payments (booking_id, method, amount, status) VALUES (%s,%s,%s,'PENDING')", (bid, method, total))
        payments.get_payment(method).reserve_seats(showtime_id, [l["seat_id"] for l in tl])
    return bid, total


def finalize_paid(booking_id, method, emp_id=None, txn_ref=None):
    """Thanh toán thành công: ghế -> Đã bán, đơn -> Đã thanh toán, rồi PHÁT SỰ KIỆN BookingPaid (mẫu Observer).
    Các observer lo phần còn lại: xuất QR (UC39), trừ kho FIFO (UC44), tích điểm (UC45), thông báo + email."""
    b = q1("SELECT * FROM bookings WHERE booking_id=%s FOR UPDATE", (booking_id,))
    if not b or b["payment_status"] == "PAID":
        return
    next_state = booking_states.state_of(b["status"]).on_paid()      # mẫu State: đơn đã hủy -> ném AppError
    at = now()
    tks = q("SELECT * FROM tickets WHERE booking_id=%s AND status='VALID'", (booking_id,))
    ids = [t["seat_id"] for t in tks]
    run("UPDATE showtime_seats SET status='SOLD', held_by=NULL, held_until=NULL WHERE showtime_id=%s AND seat_id IN ("
        + in_clause(ids) + ")", (b["showtime_id"], *ids))
    run("UPDATE bookings SET payment_status='PAID', status=%s WHERE booking_id=%s", (next_state.code, booking_id))
    run("UPDATE payments SET status='SUCCESS', method=%s, paid_at=%s, transaction_ref=%s WHERE booking_id=%s",
        (method, at, txn_ref, booking_id))
    booking_paid.notify(BookingPaid(booking=b, method=method, emp_id=emp_id, txn_ref=txn_ref, paid_at=at, tickets=tks))


def cancel_booking_internal(booking_id, reason, refund=0, tickets=None):
    """Hủy các vé còn hiệu lực của đơn (tất cả hoặc danh sách ticket_id), trả ghế về Trống."""
    b = q1("SELECT * FROM bookings WHERE booking_id=%s", (booking_id,))
    sql = "SELECT * FROM tickets WHERE booking_id=%s AND status='VALID'"
    args = [booking_id]
    if tickets:
        sql += " AND ticket_id IN (" + in_clause(tickets) + ")"
        args += list(tickets)
    tks = q(sql, tuple(args))
    for t in tks:
        run("UPDATE tickets SET status='CANCELLED' WHERE ticket_id=%s", (t["ticket_id"],))
        run("UPDATE showtime_seats SET status='AVAILABLE', held_by=NULL, held_until=NULL WHERE showtime_id=%s AND seat_id=%s",
            (t["showtime_id"], t["seat_id"]))
    left = q1("SELECT COUNT(*) AS n FROM tickets WHERE booking_id=%s AND status='VALID'", (booking_id,))["n"]
    if left == 0:
        new_state = (booking_states.state_of(b["status"]) if b else booking_states.PENDING_CONFIRM).on_all_tickets_cancelled()
        run("UPDATE bookings SET status=%s, cancelled_at=%s, refund_amount=refund_amount+%s, "
            "payment_status=CASE WHEN payment_status='PAID' AND %s>0 THEN 'REFUNDED' ELSE payment_status END "
            "WHERE booking_id=%s", (new_state.code, now(), refund, refund, booking_id))
        run("UPDATE payments SET status=CASE WHEN status='SUCCESS' AND %s>0 THEN 'REFUNDED' WHEN status='PENDING' THEN 'FAILED' "
            "ELSE status END WHERE booking_id=%s", (refund, booking_id))
    else:
        run("UPDATE bookings SET refund_amount=refund_amount+%s WHERE booking_id=%s", (refund, booking_id))
    return tks
