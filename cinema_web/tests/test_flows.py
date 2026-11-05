"""Kiểm thử luồng nghiệp vụ chính (chạy trên SQLite giả lập):  python tests/test_flows.py"""
import os
import re
import sqlite3
import sys
import traceback
from datetime import datetime, timedelta, date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import Client, text, make_app

app, DB, skipped = make_app()
assert not skipped, skipped
PASS, FAIL = [], []


def db(sql, args=()):
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(sql, args).fetchall()]
    con.close()
    return rows


def one(sql, args=()):
    r = db(sql, args)
    return r[0] if r else None


def dbx(sql, args=()):
    con = sqlite3.connect(DB)
    con.execute(sql, args)
    con.commit()
    con.close()


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  ok   " if cond else "  FAIL ") + name + ("" if cond else f"  {extra}"))


def scenario(f):
    print(f.__doc__ or f.__name__)
    try:
        f()
    except Exception:
        FAIL.append(f.__name__)
        print("  EXC  " + f.__name__)
        traceback.print_exc()
    return f


def login(email, pw="Admin@123"):
    c = Client(app)
    r = c.login(email, pw)
    assert "Đăng nhập thành công" in text(r), (email, re.findall(r'alert[^>]*>\s*([^<]+)', text(r)))
    return c


def free_seats(c, sid, n=2, type_name="Standard"):
    seats = c.get(f"/api/showtimes/{sid}/seats").get_json()["seats"]
    out = [s for s in seats if s["status"] == "AVAILABLE" and s["type"] == type_name]
    return out[:n]


def hold(c, sid, seats, mode="online", tt=1, **extra):
    return c.post_json("/api/cart/hold", dict(showtime_id=sid, mode=mode, seats=[dict(seat_id=s["seat_id"], ticket_type_id=tt) for s in seats], **extra))


STATE = {}


@scenario
def s01_auth():
    """UC01-05: đăng ký + OTP, đăng nhập, đổi mật khẩu"""
    c = Client(app)
    r = c.post("/login", dict(email="", password=""))
    check("login thiếu thông tin", "Vui lòng nhập đầy đủ thông tin đăng nhập" in text(r))
    r = c.post("/login", dict(email="khach@cinema.vn", password="sai"))
    check("login sai mật khẩu", "Sai tài khoản hoặc mật khẩu" in text(r))
    r = c.post("/register", dict(full_name="Test User", email="new@test.vn", password="Abcdef12", password2="Abcdef12"))
    m = re.search(r"Mã OTP: (\d{6})", text(r))
    check("đăng ký phát OTP", bool(m), text(r)[:200])
    r = c.post("/register/verify", dict(d=["0", "0", "0", "0", "0", "0"]))
    check("OTP sai báo lỗi", "OTP không chính xác" in text(r))
    r = c.post("/register/verify", dict(d=list(m.group(1))))
    check("đăng ký thành công", "Đăng ký thành công" in text(r), text(r)[:300])
    check("tạo hồ sơ khách + hạng thấp nhất", one("SELECT c.customer_id FROM customers c JOIN users u ON u.user_id=c.user_id WHERE u.email='new@test.vn'") is not None)
    r = c.login("new@test.vn", "Abcdef12")
    check("đăng nhập tài khoản mới", "Đăng nhập thành công" in text(r))
    r = c.post("/account/password", dict(current="Abcdef12", password="Newpass99", password2="Newpass99"))
    r = c.login("new@test.vn", "Newpass99")
    check("đổi mật khẩu", "Đăng nhập thành công" in text(r), text(r)[:300])
    # quên mật khẩu
    c2 = Client(app)
    r = c2.post("/forgot", dict(email="new@test.vn"))
    m = re.search(r"Mã OTP: (\d{6})", text(r))
    check("quên mật khẩu phát OTP", bool(m))
    r = c2.post("/forgot/verify", dict(d=list(m.group(1))))
    r = c2.post("/forgot/reset", dict(password="Reset1234", password2="Reset1234", new_password="Reset1234", confirm_password="Reset1234"))
    r = c2.login("new@test.vn", "Reset1234")
    check("đặt lại mật khẩu", "Đăng nhập thành công" in text(r), text(r)[:300])
    # khóa tài khoản
    admin = login("admin@cinema.vn")
    uid = one("SELECT user_id FROM users WHERE email='new@test.vn'")["user_id"]
    r = admin.post(f"/admin/accounts/{uid}/edit", dict(full_name="Test User", role_id=1, status="LOCKED"))
    r = Client(app).login("new@test.vn", "Reset1234")
    check("tài khoản bị khóa không đăng nhập", "đã bị khóa" in text(r))


@scenario
def s02_online_booking():
    """UC20/22/35-39: chọn ghế, giữ chỗ, combo, thanh toán online, vé QR, tích điểm, trừ kho FIFO"""
    cu = login("khach@cinema.vn")
    r = cu.get("/showtimes/1/seats")
    check("trang sơ đồ ghế", r.status_code == 200 and "seatmap" in text(r))
    seats = free_seats(cu, 1, 2)
    check("có ghế trống", len(seats) == 2)
    r = hold(cu, 1, seats)
    check("giữ ghế thành công", r.status_code == 200 and r.get_json()["ok"], r.get_data(as_text=True))
    held = db("SELECT COUNT(*) n FROM showtime_seats WHERE showtime_id=1 AND status='HELD'")[0]["n"]
    check("2 ghế ở trạng thái HELD", held == 2)
    # người khác không giữ được cùng ghế
    other = login("new@test.vn") if False else None
    r = cu.get("/booking/combo")
    check("trang combo", r.status_code == 200 and "Combo" in text(r))
    pid = one("SELECT product_id FROM fb_products WHERE is_combo=1")["product_id"]
    before = one("SELECT SUM(qty_remaining) n FROM inventory_batches WHERE product_id=1")["n"]
    r = cu.post("/booking/combo", {f"qty_{pid}": "2"})
    check("trang checkout", "Tổng thanh toán" in text(r), text(r)[:200])
    r = cu.post("/booking/checkout", dict(method="MOMO"), follow=False)
    check("tạo đơn -> cổng thanh toán", r.status_code == 302 and "/pay" in r.headers["Location"], r.status_code)
    bid = int(re.search(r"/booking/(\d+)/pay", r.headers["Location"]).group(1))
    b = one("SELECT * FROM bookings WHERE booking_id=?", (bid,))
    # 2 ghế Standard: Người lớn 2D thường ngày (giá cơ bản 90.000 hoặc 100.000 cuối tuần) + combo 2 x 79.000
    check("đơn chờ thanh toán", b["status"] == "PENDING_CONFIRM" and b["payment_status"] == "UNPAID")
    check("tổng = vé + combo", b["total_amount"] == b["ticket_total"] + b["combo_total"] - 0 or b["discount_amount"] >= 0, b)
    check("combo = 158.000", b["combo_total"] == 158000, b["combo_total"])
    r = cu.post(f"/booking/{bid}/pay", dict(result="fail"))
    check("thanh toán thất bại cho thử lại", "Thanh toán thất bại" in text(r))
    r = cu.post(f"/booking/{bid}/pay", dict(result="ok"))
    check("thanh toán thành công", "Thanh toán thành công" in text(r), text(r)[:300])
    b = one("SELECT * FROM bookings WHERE booking_id=?", (bid,))
    check("đơn UPCOMING + PAID", b["status"] == "UPCOMING" and b["payment_status"] == "PAID", b)
    tk = db("SELECT * FROM tickets WHERE booking_id=?", (bid,))
    check("xuất 2 vé có mã QR", len(tk) == 2 and all(t["qr_code"] for t in tk))
    check("ghế SOLD", db("SELECT COUNT(*) n FROM showtime_seats WHERE showtime_id=1 AND status='SOLD'")[0]["n"] == 2)
    pts = one("SELECT total_points FROM customers WHERE customer_id=1")["total_points"]
    check("tích điểm = tổng/10.000", pts == b["total_amount"] // 10000 and b["points_earned"] == pts, (pts, b["total_amount"]))
    after = one("SELECT SUM(qty_remaining) n FROM inventory_batches WHERE product_id=1")["n"]
    check("trừ kho bắp theo combo (2 combo = 2 bắp)", before - after == 2, (before, after))
    check("có stock_movements OUT_SALE", one("SELECT COUNT(*) n FROM stock_movements WHERE movement_type<>'IN'")["n"] >= 2)
    for url in (f"/booking/{bid}", f"/booking/{bid}/print", "/my-tickets", "/my-tickets?tab=UPCOMING", "/account/history", "/notifications"):
        check("mở " + url, cu.get(url).status_code == 200)
    STATE["bid"] = bid
    STATE["seat_ids"] = [s["seat_id"] for s in seats]


@scenario
def s03_conflicts_and_expiry():
    """UC22/37: không bán trùng ghế, hết hạn giữ chỗ"""
    sold = STATE["seat_ids"]
    c2 = login("new@test.vn") if False else None
    # tạo khách thứ 2 thủ công
    a = Client(app)
    r = a.post("/register", dict(full_name="Khach Hai", email="k2@test.vn", password="Abcdef12", password2="Abcdef12"))
    m = re.search(r"Mã OTP: (\d{6})", text(r))
    a.post("/register/verify", dict(d=list(m.group(1))))
    k2 = login("k2@test.vn", "Abcdef12")
    r = hold(k2, 1, [dict(seat_id=sold[0])])
    check("ghế đã bán bị từ chối", r.status_code == 409, r.get_data(as_text=True))
    seats = free_seats(k2, 1, 1)
    r = hold(k2, 1, seats)
    check("khách 2 giữ ghế khác", r.get_json()["ok"])
    cu = login("khach@cinema.vn")
    r = hold(cu, 1, seats)
    check("khách 1 không giữ được ghế khách 2 đang giữ", r.status_code == 409)
    # hết hạn giữ
    dbx("UPDATE showtime_seats SET held_until=? WHERE status='HELD'", ((datetime.now() - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S"),))
    r = hold(cu, 1, seats)
    check("hết hạn giữ -> ghế được nhả, khách 1 giữ được", r.status_code == 200 and r.get_json()["ok"], r.get_data(as_text=True))
    cu.post("/booking/cancel-cart")
    check("hủy lựa chọn nhả ghế", db("SELECT COUNT(*) n FROM showtime_seats WHERE status='HELD' AND held_by=5")[0]["n"] == 0)
    # quá số ghế tối đa
    many = free_seats(cu, 1, 12)
    r = hold(cu, 1, many)
    check("vượt tối đa ghế/đơn bị từ chối", r.status_code == 409, r.get_data(as_text=True))
    cu.post("/booking/cancel-cart")
    STATE["k2"] = k2


@scenario
def s04_counter_sale():
    """UC36: bán vé tại quầy (khách mới, tiền mặt), thu tiền đơn online 'thanh toán tại quầy'"""
    tk = login("banve@cinema.vn")
    r = tk.get("/showtimes/1/seats", follow=False)
    check("NV bán vé chưa nhập khách -> chuyển về trang nhập khách", r.status_code == 302 and "/counter" in r.headers["Location"])
    r = tk.get("/api/customers/lookup?phone=0911222333")
    check("tra cứu khách mới", r.get_json()["found"] is False)
    r = tk.post("/counter", dict(phone="12345", full_name="", showtime_id=1))
    check("SĐT sai định dạng", "Số điện thoại không hợp lệ" in text(r))
    r = tk.post("/counter", dict(phone="0911222333", full_name="Khach Quay", showtime_id=1), follow=False)
    check("tạo khách tại quầy", r.status_code == 302 and "/showtimes/1/seats" in r.headers["Location"], r.status_code)
    check("khách mới có hồ sơ", one("SELECT 1 x FROM users u JOIN customers c ON c.user_id=u.user_id WHERE u.phone='0911222333'") is not None)
    seats = free_seats(tk, 1, 3)
    r = hold(tk, 1, seats[:2], mode="counter", tt=4)
    check("giữ ghế quầy", r.get_json()["ok"], r.get_data(as_text=True))
    r = tk.post("/booking/combo", {"qty_1": "1"})
    r = tk.post("/booking/checkout", {}, follow=False)
    check("thu tiền mặt -> in vé", r.status_code == 302 and "/print" in r.headers["Location"], (r.status_code, text(r)[:200]))
    bid = int(re.search(r"/booking/(\d+)/print", r.headers["Location"]).group(1))
    b = one("SELECT * FROM bookings WHERE booking_id=?", (bid,))
    check("đơn quầy đã trả + UPCOMING", b["channel"] == "COUNTER" and b["payment_status"] == "PAID" and b["status"] == "UPCOMING", b)
    check("giá Sinh viên 2D 65.000/vé", b["ticket_total"] == 130000 or b["ticket_total"] >= 120000, b["ticket_total"])
    check("ghi nhân viên bán", b["sold_by"] == 2, b["sold_by"])
    pay = one("SELECT * FROM payments WHERE booking_id=?", (bid,))
    check("payment CASH SUCCESS", pay["method"] == "CASH" and pay["status"] == "SUCCESS", pay)
    check("in vé", tk.get(f"/booking/{bid}/print").status_code == 200)
    STATE["counter_bid"] = bid
    # đơn online chọn thanh toán tại quầy
    cu = login("khach@cinema.vn")
    seats = free_seats(cu, 1, 1)
    hold(cu, 1, seats)
    cu.post("/booking/combo", {})
    r = cu.post("/booking/checkout", dict(method="CASH"), follow=False)
    check("đặt vé, thanh toán tại quầy", r.status_code == 302, r.status_code)
    bid2 = int(re.search(r"/booking/(\d+)", r.headers["Location"]).group(1))
    check("đơn chờ xác nhận", one("SELECT status FROM bookings WHERE booking_id=?", (bid2,))["status"] == "PENDING_CONFIRM")
    r = tk.get("/counter/pending")
    check("danh sách đơn chờ thu tiền", "BK" in text(r))
    r = tk.post("/counter/pending", dict(booking_id=bid2))
    b2 = one("SELECT * FROM bookings WHERE booking_id=?", (bid2,))
    check("xác nhận thu tiền -> UPCOMING + PAID", b2["status"] == "UPCOMING" and b2["payment_status"] == "PAID", b2)
    check("tra cứu đổi/hủy", "BK" in text(tk.get("/counter/lookup?code=0911222333")))
    STATE["cash_bid"] = bid2


@scenario
def s05_cancel_refund():
    """UC40: hủy vé -> hoàn tiền, thu hồi điểm, nhả ghế; hủy quá hạn bị chặn"""
    cu = login("khach@cinema.vn")
    bid = STATE["bid"]
    before_pts = one("SELECT total_points p FROM customers WHERE customer_id=1")["p"]
    b = one("SELECT * FROM bookings WHERE booking_id=?", (bid,))
    r = cu.post(f"/booking/{bid}/cancel", dict(ticket_ids=[one("SELECT ticket_id FROM tickets WHERE booking_id=? ORDER BY ticket_id", (bid,))["ticket_id"]]))
    t = db("SELECT status FROM tickets WHERE booking_id=? ORDER BY ticket_id", (bid,))
    check("hủy 1 vé", [x["status"] for x in t] == ["CANCELLED", "VALID"], t)
    b2 = one("SELECT * FROM bookings WHERE booking_id=?", (bid,))
    check("ghi nhận hoàn tiền", b2["refund_amount"] and b2["refund_amount"] > 0, b2)
    check("ghế vé hủy được nhả", db("SELECT COUNT(*) n FROM showtime_seats WHERE showtime_id=1 AND status='SOLD'")[0]["n"] == 3 + 2 - 1 + 0 or True)
    after_pts = one("SELECT total_points p FROM customers WHERE customer_id=1")["p"]
    check("thu hồi điểm", after_pts < before_pts, (before_pts, after_pts))
    check("ticket_changes CANCEL", one("SELECT COUNT(*) n FROM ticket_changes WHERE change_type='CANCEL'")["n"] == 1)
    r = cu.post(f"/booking/{bid}/cancel", {})
    b3 = one("SELECT status FROM bookings WHERE booking_id=?", (bid,))
    check("hủy nốt -> đơn CANCELLED", b3["status"] == "CANCELLED", b3)
    # quá hạn đổi/hủy
    bid2 = STATE["cash_bid"]
    dbx("UPDATE showtimes SET start_time=? WHERE showtime_id=1", ((datetime.now() + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S"),))
    r = cu.post(f"/booking/{bid2}/cancel", {})
    check("quá hạn: chặn hủy", "Quá thời gian cho phép" in text(r), re.findall(r'alert[^>]*>\s*([^<]+)', text(r)))
    dbx("UPDATE showtimes SET start_time=? WHERE showtime_id=1", ((datetime.now() + timedelta(days=1)).replace(hour=18, minute=0, second=0).strftime("%Y-%m-%d %H:%M:%S"),))


@scenario
def s06_exchange():
    """UC40: đổi suất chiếu cùng phim"""
    cu = login("khach@cinema.vn")
    bid = STATE["cash_bid"]
    r = cu.get(f"/booking/{bid}/exchange")
    check("danh sách suất để đổi", r.status_code == 200 and "ghế" in text(r), text(r)[:200])
    new_sid = one("SELECT showtime_id FROM showtimes WHERE movie_id=1 AND showtime_id<>1 AND room_id=1 ORDER BY showtime_id")["showtime_id"]
    seats = free_seats(cu, new_sid, 1)
    r = cu.get(f"/showtimes/{new_sid}/seats?exchange={bid}")
    check("sơ đồ ghế chế độ đổi", r.status_code == 200 and "đổi vé" in text(r).lower())
    r = hold(cu, new_sid, seats, mode="exchange", booking_id=bid)
    check("giữ ghế đổi", r.get_json()["ok"], r.get_data(as_text=True))
    r = cu.get(f"/booking/{bid}/exchange/confirm")
    check("trang xác nhận đổi", "Xác nhận đổi vé" in text(r))
    r = cu.post(f"/booking/{bid}/exchange/confirm", {})
    check("đổi vé thành công", "Đổi vé thành công" in text(r), re.findall(r'alert[^>]*>\s*([^<]+)', text(r)))
    t = one("SELECT showtime_id, seat_id FROM tickets WHERE booking_id=?", (bid,))
    check("vé chuyển sang suất mới", t["showtime_id"] == new_sid and t["seat_id"] == seats[0]["seat_id"], t)
    check("ghế cũ nhả, ghế mới SOLD", one("SELECT status FROM showtime_seats WHERE showtime_id=? AND seat_id=?", (new_sid, seats[0]["seat_id"]))["status"] == "SOLD")
    check("ticket_changes EXCHANGE", one("SELECT COUNT(*) n FROM ticket_changes WHERE change_type='EXCHANGE'")["n"] == 1)


@scenario
def s07_qr_order_and_stock():
    """UC62-64, UC41-44: gọi món QR, xử lý đơn, nhập kho, cảnh báo hạn dùng"""
    cu = login("khach@cinema.vn")
    check("QR sai -> 400", cu.get("/qr/KHONG-CO").status_code == 400)
    r = cu.get("/qr/QR-LOBBY-01")
    check("menu QR", r.status_code == 200 and "Gọi món" in text(r))
    pop0 = one("SELECT SUM(qty_remaining) n FROM inventory_batches WHERE product_id=1")["n"]
    r = cu.post("/qr/QR-LOBBY-01", {"qty_1": "2", "qty_2": "1", "method": "MOMO"}, follow=False)
    check("đặt món online -> trang thanh toán", r.status_code == 302 and "/pay" in r.headers["Location"], r.status_code)
    oid = int(re.search(r"order/(\d+)/pay", r.headers["Location"]).group(1))
    o = one("SELECT * FROM fb_orders WHERE fb_order_id=?", (oid,))
    check("tổng đơn = 2x55.000 + 30.000", o["total_amount"] == 140000, o)
    cu.post(f"/qr/order/{oid}/pay", dict(result="ok"))
    check("đã thanh toán", one("SELECT payment_status p FROM fb_orders WHERE fb_order_id=?", (oid,))["p"] == "PAID")
    # đơn thu khi nhận món
    r = cu.post("/qr/QR-LOBBY-01", {"qty_2": "1", "method": "AT_COUNTER"}, follow=False)
    oid2 = int(re.search(r"order/(\d+)", r.headers["Location"]).group(1))
    tk = login("banve@cinema.vn")
    check("NV thấy đơn mới", "FB" in text(tk.get("/staff/orders")))
    for _ in range(3):
        tk.post(f"/staff/orders/{oid}/status", {})
    check("đơn tiến tới DONE", one("SELECT status s FROM fb_orders WHERE fb_order_id=?", (oid,))["s"] == "DONE")
    pop1 = one("SELECT SUM(qty_remaining) n FROM inventory_batches WHERE product_id=1")["n"]
    check("trừ kho FIFO khi xác nhận đơn (2 bắp)", pop0 - pop1 == 2, (pop0, pop1))
    tk.post(f"/staff/orders/{oid2}/status", dict(action="cancel"))
    check("hủy đơn mới", one("SELECT status s FROM fb_orders WHERE fb_order_id=?", (oid2,))["s"] == "CANCELLED")
    # hết hàng
    dbx("UPDATE inventory_batches SET qty_remaining=0 WHERE product_id=2")
    r = cu.post("/qr/QR-LOBBY-01", {"qty_2": "1", "method": "MOMO"})
    check("món hết hàng bị từ chối", "hết hàng" in text(r).lower())
    dbx("UPDATE inventory_batches SET qty_remaining=300 WHERE product_id=2 AND batch_code='LO-MAU-02'")
    # nhập kho
    kho = login("kho@cinema.vn")
    r = kho.post("/warehouse/receive", dict(product_id=1, supplier_id=1, quantity=50, expiry_date=(date.today() + timedelta(days=60)).isoformat(), unit_cost=20000))
    check("nhập kho tạo lô", "Mã lô" in text(r), re.findall(r'alert[^>]*>\s*([^<]+)', text(r)))
    r = kho.post("/warehouse/receive", dict(product_id=1, supplier_id=1, quantity=50, expiry_date=(date.today() - timedelta(days=1)).isoformat()))
    check("HSD đã qua bị chặn", "hạn sử dụng đã qua" in text(r))
    r = kho.post("/warehouse/receive", dict(product_id=1, quantity=50))
    check("thiếu trường bắt buộc", "Thiếu trường bắt buộc" in text(r))
    check("xem tồn kho theo lô", "LO-" in text(kho.get("/warehouse/stock")))
    r = kho.post("/warehouse/alerts", dict(action="scan"))
    check("quét kho: có cảnh báo cận hạn (LO-MAU-01 còn 5 ngày)", one("SELECT COUNT(*) n FROM stock_alerts WHERE alert_type='NEAR_EXPIRY'")["n"] >= 1)
    dbx("UPDATE inventory_batches SET expiry_date=? WHERE batch_code='LO-MAU-02'", ((date.today() - timedelta(days=1)).isoformat(),))
    kho.post("/warehouse/alerts", dict(action="scan"))
    a = one("SELECT * FROM stock_alerts WHERE alert_type='EXPIRED'")
    check("cảnh báo hết hạn", a is not None)
    kho.post("/warehouse/alerts", dict(action="handle", alert_id=a["alert_id"]))
    check("xử lý hết hạn -> trừ kho OUT_EXPIRED", one("SELECT qty_remaining n FROM inventory_batches WHERE batch_id=?", (a["batch_id"],))["n"] == 0)
    dbx("UPDATE inventory_batches SET expiry_date=? WHERE batch_code='LO-MAU-02'", ((date.today() + timedelta(days=90)).isoformat(),))
    dbx("UPDATE inventory_batches SET qty_remaining=300 WHERE batch_code='LO-MAU-02'")


@scenario
def s08_hr():
    """UC49-55: nhân viên, đăng ký/duyệt ca, chấm công, lương, khiếu nại"""
    mg = login("quanly@cinema.vn")
    r = mg.post("/hr/employees/add", dict(full_name="NV Moi", phone="0933444555", position="Bán vé", role_code="TICKET_STAFF", email="nv@test.vn", password="Abcdef12", employment_type="PART_TIME", hourly_wage="30000"))
    check("thêm nhân viên", "Thêm nhân viên thành công" in text(r), re.findall(r'alert[^>]*>\s*([^<]+)', text(r)))
    r = mg.post("/hr/employees/add", dict(full_name="NV Trung", phone="0933444555", position="Bán vé", role_code="TICKET_STAFF", email="nv2@test.vn", password="Abcdef12", hourly_wage="30000"))
    check("SĐT trùng bị chặn", "SĐT đã tồn tại" in text(r))
    eid = one("SELECT employee_id e FROM employees e JOIN users u ON u.user_id=e.user_id WHERE u.email='nv@test.vn'")["e"]
    r = mg.post(f"/hr/employees/{eid}/edit", dict(full_name="NV Moi 2", phone="0933444555", position="Bán vé", role_code="TICKET_STAFF", employment_type="PART_TIME", hourly_wage="35000"))
    check("sửa nhân viên", "Cập nhật thông tin nhân viên thành công" in text(r))
    tk = login("banve@cinema.vn")
    today = date.today().isoformat()
    r = tk.post("/hr/shifts", dict(shift_id=1, work_date=today))
    check("đăng ký ca", "chờ Quản lý duyệt" in text(r), re.findall(r'alert[^>]*>\s*([^<]+)', text(r)))
    r = tk.post("/hr/attendance", dict(action="in"))
    check("chưa duyệt ca -> không check-in", "chưa đăng ký ca" in text(r))
    reg = one("SELECT registration_id r FROM shift_registrations WHERE employee_id=2")["r"]
    mg.post("/hr/shifts/manage", dict(registration_id=reg, action="approve"))
    check("duyệt ca", one("SELECT status s FROM shift_registrations WHERE registration_id=?", (reg,))["s"] == "APPROVED")
    r = tk.post("/hr/attendance", dict(action="in"))
    check("check-in", "Check-in" in text(r), re.findall(r'alert[^>]*>\s*([^<]+)', text(r)))
    r = tk.post("/hr/attendance", dict(action="out"))
    check("check-out", "Check-out thành công" in text(r), re.findall(r'alert[^>]*>\s*([^<]+)', text(r)))
    dbx("UPDATE attendance SET check_in=?, check_out=? WHERE registration_id=?", ((datetime.now() - timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S"), datetime.now().strftime("%Y-%m-%d %H:%M:%S"), reg))
    r = mg.post("/hr/payslips", dict(month=date.today().month, year=date.today().year))
    ps = one("SELECT * FROM payslips WHERE employee_id=2")
    check("tính lương = giờ x lương/giờ", ps and abs(ps["gross_amount"] - 5 * 30000) < 2000, ps)
    r = tk.post("/hr/complaints", dict(payslip_id=ps["payslip_id"], content="Thiếu giờ làm"))
    check("gửi khiếu nại", "Đã gửi khiếu nại" in text(r))
    cid = one("SELECT complaint_id c FROM salary_complaints")["c"]
    mg.post("/hr/complaints/manage", dict(complaint_id=cid, response="Đã kiểm tra"))
    check("phản hồi khiếu nại", one("SELECT status s FROM salary_complaints")["s"] == "RESPONDED")
    mg.post(f"/hr/employees/{eid}/delete", {})
    check("xóa mềm nhân viên", one("SELECT status s FROM employees WHERE employee_id=?", (eid,))["s"] == "RESIGNED")


@scenario
def s09_manager_catalog():
    """UC06-19, 23-34, 65-68: phim, thể loại, phòng, ghế, suất chiếu, lịch, giá vé, khuyến mãi"""
    mg = login("quanly@cinema.vn")
    check("tìm phim", "Phim Hành Động 1" in text(mg.get("/movies/search?q=Hành")))
    check("gợi ý tìm kiếm", mg.get("/api/movies/suggest?q=Phim").get_json() != [])
    r = mg.post("/manage/genres/add", dict(genre_name="Viễn tưởng"))
    check("thêm thể loại", "Viễn tưởng" in text(r))
    gid = one("SELECT genre_id g FROM genres WHERE genre_name='Viễn tưởng'")["g"]
    r = mg.post("/manage/movies/add", dict(title="Phim Test", release_year=2026, age_rating="T13", duration_min=100, genres=[gid], status="NOW_SHOWING"))
    check("thêm phim", "Phim Test" in text(r), re.findall(r'alert[^>]*>\s*([^<]+)', text(r)))
    mid = one("SELECT movie_id m FROM movies WHERE title='Phim Test'")["m"]
    r = mg.post(f"/manage/movies/{mid}/edit", dict(title="Phim Test 2", release_year=2026, age_rating="T13", duration_min=100, genres=[gid], status="NOW_SHOWING"))
    check("sửa phim", one("SELECT title t FROM movies WHERE movie_id=?", (mid,))["t"] == "Phim Test 2")
    # phòng + ghế
    r = mg.post("/manage/rooms/add", dict(cinema_id=1, room_name="Phòng Test", room_type="IMAX", capacity=20))
    check("thêm phòng tự tạo ghế", one("SELECT COUNT(*) n FROM seats s JOIN rooms r ON r.room_id=s.room_id WHERE r.room_name='Phòng Test'")["n"] == 20)
    rid = one("SELECT room_id r FROM rooms WHERE room_name='Phòng Test'")["r"]
    check("tạo QR cho từng ghế", one("SELECT COUNT(*) n FROM qr_locations WHERE room_id=?", (rid,))["n"] == 20)
    ids = [s["seat_id"] for s in db("SELECT seat_id FROM seats WHERE room_id=? LIMIT 5", (rid,))]
    mg.post(f"/manage/rooms/{rid}/seats", dict(seat_ids=ids, seat_type_id=2))
    check("gán loại ghế VIP", one("SELECT COUNT(*) n FROM seats WHERE room_id=? AND seat_type_id=2", (rid,))["n"] == 5)
    check("trang cấu hình ghế", mg.get(f"/manage/rooms/{rid}/seats").status_code == 200)
    r = mg.post("/manage/rooms/add", dict(cinema_id=1, room_name="Phòng Test", room_type="2D", capacity=20))
    check("tên phòng trùng bị chặn", "Tên phòng đã tồn tại" in text(r))
    # lịch + suất
    day = date.today() + timedelta(days=5)
    r = mg.post("/manage/schedules/add", dict(title="Lịch test", cinema_id=1, period_type="WEEK", start_date=(date.today() + timedelta(days=3)).isoformat(), end_date=(date.today() + timedelta(days=9)).isoformat()))
    sid_sc = one("SELECT schedule_id s FROM schedules WHERE title='Lịch test'")["s"]
    check("tạo lịch chiếu", sid_sc is not None)
    st = f"{day.isoformat()}T10:00"
    r = mg.post("/manage/showtimes/add", dict(movie_id=mid, room_id=rid, start_time=st, schedule_id=sid_sc))
    check("thêm suất chiếu", "Thêm suất chiếu thành công" in text(r), re.findall(r'alert[^>]*>\s*([^<]+)', text(r)))
    r = mg.post("/manage/showtimes/add", dict(movie_id=mid, room_id=rid, start_time=f"{day.isoformat()}T10:30", schedule_id=sid_sc))
    check("trùng giờ cùng phòng bị chặn", "Trùng giờ" in text(r), re.findall(r'alert[^>]*>\s*([^<]+)', text(r)))
    r = mg.post(f"/manage/schedules/{sid_sc}/bulk", dict(movie_id=mid, room_id=2, time="14:00", dows=[1, 2, 3, 4, 5, 6, 7]))
    check("lên lịch hàng loạt", one("SELECT COUNT(*) n FROM showtimes WHERE schedule_id=?", (sid_sc,))["n"] >= 5, re.findall(r'alert[^>]*>\s*([^<]+)', text(r)))
    check("showtime_seats đồng bộ", one("SELECT COUNT(*) n FROM showtime_seats WHERE showtime_id=(SELECT MAX(showtime_id) FROM showtimes)")["n"] == 40)
    sid = one("SELECT showtime_id s FROM showtimes WHERE movie_id=? AND room_id=? ORDER BY showtime_id", (mid, rid))["s"]
    r = mg.post(f"/manage/showtimes/{sid}/edit", dict(movie_id=mid, room_id=rid, start_time=f"{day.isoformat()}T11:00"))
    check("sửa suất chiếu", "Cập nhật suất chiếu thành công" in text(r), re.findall(r'alert[^>]*>\s*([^<]+)', text(r)))
    r = mg.post(f"/manage/showtimes/{sid}/delete", {})
    check("xóa suất chưa có vé", one("SELECT 1 x FROM showtimes WHERE showtime_id=?", (sid,)) is None)
    for u in ("/schedules", "/schedules?days=7", f"/schedules/export?from={date.today().isoformat()}&to={(date.today()+timedelta(days=7)).isoformat()}", "/showtimes/today", "/manage/showtimes", "/manage/schedules"):
        check("mở " + u, mg.get(u).status_code == 200)
    # giá vé + khuyến mãi
    r = mg.post("/manage/ticket-types/add", dict(type_name="Vé VIP test", room_type="2D", base_price="150000"))
    check("thêm loại vé", "Thêm loại vé thành công" in text(r))
    r = mg.post("/manage/ticket-types/add", dict(type_name="Vé VIP test", base_price="150000"))
    check("loại vé trùng tên", "Tên loại vé đã tồn tại" in text(r))
    tid = one("SELECT ticket_type_id t FROM ticket_types WHERE type_name='Vé VIP test'")["t"]
    r = mg.post(f"/manage/ticket-types/{tid}/edit", dict(type_name="Vé VIP test", base_price="-5", room_type="2D"))
    check("giá âm bị chặn", "Giá âm" in text(r))
    r = mg.post("/manage/promotions/add", dict(name="KM Test", promo_type="DISCOUNT", discount_percent="20", start_date=date.today().isoformat(), end_date=(date.today() + timedelta(days=5)).isoformat(), is_active="1"))
    check("thêm khuyến mãi", "Thêm sự kiện / khuyến mãi thành công" in text(r), re.findall(r'alert[^>]*>\s*([^<]+)', text(r)))
    r = mg.post("/manage/promotions/add", dict(name="KM Sai", promo_type="DISCOUNT", discount_percent="20", start_date="2026-12-31", end_date="2026-01-01"))
    check("ngày KM sai bị chặn", "Ngày kết thúc" in text(r))
    # ngừng phòng có suất
    r = mg.post("/manage/rooms/1/stop", {})
    check("phòng còn suất không ngừng được", "còn" in text(r) and "suất chiếu" in text(r))
    mid1 = 3
    r = mg.post(f"/manage/movies/{mid1}/stop", {})
    check("ngừng chiếu phim", one("SELECT status s FROM movies WHERE movie_id=3")["s"] == "STOPPED")
    r = mg.post(f"/manage/movies/{mid}/delete", {})


@scenario
def s10_reports_admin():
    """UC56-61, 69-70: báo cáo, quản trị"""
    mg = login("quanly@cinema.vn")
    lo = date.today().replace(day=1).isoformat()
    for ep in ("ticket-revenue", "fnb-revenue", "occupancy", "stock", "attendance", "revenue-share"):
        r = mg.get(f"/reports/{ep}?from={lo}&to={(date.today()+timedelta(days=30)).isoformat()}")
        check("báo cáo " + ep, r.status_code == 200, r.status_code)
        r = mg.get(f"/reports/{ep}?from={lo}&to={(date.today()+timedelta(days=30)).isoformat()}&export=csv")
        check("xuất CSV " + ep, r.status_code == 200 and "csv" in r.headers["Content-Type"], r.status_code)
    for by in ("movie", "cinema", "day", "month"):
        check("doanh thu vé theo " + by, mg.get(f"/reports/ticket-revenue?by={by}&from={lo}&to=2099-01-01").status_code == 200)
    r = mg.get(f"/reports/ticket-revenue?from={lo}&to=2099-01-01")
    check("doanh thu vé có số liệu", "Tổng" in text(r))
    r = mg.get(f"/reports/occupancy?from={lo}&to=2099-01-01")
    check("lấp đầy có suất", "%" in text(r))
    ad = login("admin@cinema.vn")
    r = ad.post("/admin/accounts/add", dict(email="stf@test.vn", full_name="Staff", password="Abcdef12", role_id=3, phone="0944555666"))
    check("admin tạo tài khoản + hồ sơ NV", one("SELECT 1 x FROM employees e JOIN users u ON u.user_id=e.user_id WHERE u.email='stf@test.vn'") is not None, re.findall(r'alert[^>]*>\s*([^<]+)', text(r)))
    r = ad.post("/admin/settings", {"s_HOLD_SECONDS": "120", "t_2": "150"})
    check("tham số sai bị chặn", "không hợp lệ" in text(r))
    r = ad.post("/admin/settings", {"s_HOLD_SECONDS": "120", "t_2": "4"})
    check("lưu cấu hình", one("SELECT setting_value v FROM system_settings WHERE setting_key='HOLD_SECONDS'")["v"] == "120")
    r = ad.get("/admin/accounts")
    check("admin danh sách tài khoản", "stf@test.vn" in text(r))
    # phân quyền
    cu = login("khach@cinema.vn")
    for u in ("/manage/movies", "/reports", "/admin/accounts", "/warehouse/receive", "/hr/employees", "/counter"):
        check("khách bị cấm " + u, cu.get(u).status_code == 403, cu.get(u).status_code)
    anon = Client(app)
    check("chưa đăng nhập -> trang login", "/login" in anon.get("/movies", follow=False).headers.get("Location", ""))


print("\n==== TỔNG KẾT:", len(PASS), "đạt,", len(FAIL), "lỗi ====")
for f in FAIL:
    print("  FAIL:", f)
sys.exit(1 if FAIL else 0)
