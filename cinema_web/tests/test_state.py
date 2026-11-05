"""Kiểm thử mẫu State (cinema/booking_states.py):  python tests/test_state.py"""
import os
import sqlite3
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import Client, text, make_app  # noqa: E402

app, DB, skipped = make_app()
PASS, FAIL = [], []


def check(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print(("  ok   " if cond else "  LOI  ") + name + ("" if cond else f"   {info}"))


def db(sql, args=()):
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(sql, args).fetchall()]
    con.close()
    return rows


from cinema import booking_states as bs  # noqa: E402
from cinema.services import AppError  # noqa: E402

# ---------- đơn vị ----------
check("5 trạng thái đúng thứ tự", [s.code for s in bs.ALL] == ["PENDING_CONFIRM", "UPCOMING", "IN_PROGRESS", "COMPLETED", "CANCELLED"])
check("nhãn tiếng Việt giữ nguyên như bản cũ", bs.LABELS == {
    "PENDING_CONFIRM": "Chờ xác nhận", "UPCOMING": "Sắp tới", "IN_PROGRESS": "Đang thực hiện",
    "COMPLETED": "Đã hoàn tất", "CANCELLED": "Đã hủy"})
check("chỉ PENDING_CONFIRM và UPCOMING được đổi/hủy",
      [s.code for s in bs.ALL if s.can_change] == ["PENDING_CONFIRM", "UPCOMING"])
for code in ("IN_PROGRESS", "COMPLETED", "CANCELLED"):
    try:
        bs.state_of(code).require_changeable("hủy")
        check(f"{code}: hủy bị chặn", False)
    except AppError as e:
        check(f"{code}: hủy bị chặn đúng thông báo", str(e) == "Đơn hàng này không thể hủy", str(e))
try:
    bs.CANCELLED.require_changeable("đổi vé")
except AppError as e:
    check("thông báo đổi vé đúng", str(e) == "Đơn hàng này không thể đổi vé", str(e))
check("PENDING/UPCOMING: require_changeable không ném lỗi",
      bs.PENDING_CONFIRM.require_changeable("hủy") is None and bs.UPCOMING.require_changeable("đổi vé") is None)
check("thanh toán: PENDING_CONFIRM -> UPCOMING", bs.PENDING_CONFIRM.on_paid() is bs.UPCOMING)
try:
    bs.CANCELLED.on_paid()
    check("đơn đã hủy không thanh toán được", False)
except AppError as e:
    check("đơn đã hủy không thanh toán được", str(e) == "Đơn hàng đã bị hủy")
check("hủy hết vé -> CANCELLED", bs.UPCOMING.on_all_tickets_cancelled() is bs.CANCELLED
      and bs.PENDING_CONFIRM.on_all_tickets_cancelled() is bs.CANCELLED)
try:
    bs.state_of("KHONG_CO")
    check("mã lạ -> KeyError", False)
except KeyError:
    check("mã lạ -> KeyError", True)


def original_eff_status(status, st, en, n):
    if status in ("CANCELLED", "PENDING_CONFIRM"):
        return status
    return "UPCOMING" if n < st else ("IN_PROGRESS" if n <= en else "COMPLETED")


start = datetime(2026, 11, 1, 19, 0)
end = start + timedelta(hours=2)
cases = 0
same = 0
for status in ("PENDING_CONFIRM", "UPCOMING", "IN_PROGRESS", "COMPLETED", "CANCELLED"):
    for off in (-300, -1, 0, 1, 60, 119, 120, 121, 500):
        n = start + timedelta(minutes=off)
        cases += 1
        same += bs.display_state(status, start, end, n).code == original_eff_status(status, start, end, n)
check(f"display_state == bản gốc eff_status trên {cases} tổ hợp", same == cases)

# ---------- tích hợp ----------
cu = Client(app)
cu.login("khach@cinema.vn")
with app.app_context():
    from cinema import services as sv
    seats = [s_ for s_ in sv.seat_map(1, None) if s_["status"] == "AVAILABLE"][:2]
cu.post_json("/api/cart/hold", dict(showtime_id=1, mode="online", seats=[dict(seat_id=s_["seat_id"], ticket_type_id=1) for s_ in seats]))
cu.post("/booking/combo", {})
r = cu.post("/booking/checkout", dict(method="MOMO"), follow=False)
bid = int(r.headers["Location"].split("/booking/")[1].split("/")[0])
check("đơn mới ở trạng thái PENDING_CONFIRM", db("SELECT status FROM bookings WHERE booking_id=?", (bid,))[0]["status"] == "PENDING_CONFIRM")
check("trang chi tiết hiển thị 'Chờ xác nhận' và cho phép hủy",
      "Chờ xác nhận" in text(cu.get(f"/booking/{bid}")))
r = cu.post(f"/booking/{bid}/cancel", {})
check("hủy đơn đang chờ -> CANCELLED", db("SELECT status FROM bookings WHERE booking_id=?", (bid,))[0]["status"] == "CANCELLED", text(r)[:200])
r = cu.post(f"/booking/{bid}/cancel", {})
check("hủy lần 2 bị chặn bởi State", "Đơn hàng này không thể hủy" in text(r))
r = cu.get(f"/booking/{bid}/exchange")
check("đổi vé đơn đã hủy bị chặn bởi State", "Đơn hàng này không thể đổi vé" in text(r))
with app.app_context():
    try:
        sv.finalize_paid(bid, "MOMO")
        check("finalize_paid đơn đã hủy -> AppError", False)
    except AppError as e:
        check("finalize_paid đơn đã hủy -> AppError", str(e) == "Đơn hàng đã bị hủy")
check("tab 'Đã hủy' của Vé của tôi có đơn", "Đã hủy" in text(cu.get("/my-tickets?tab=CANCELLED")))

# đơn đã thanh toán: PENDING -> UPCOMING qua on_paid()
cu.post_json("/api/cart/hold", dict(showtime_id=1, mode="online", seats=[dict(seat_id=seats[0]["seat_id"], ticket_type_id=1)]))
cu.post("/booking/combo", {})
r = cu.post("/booking/checkout", dict(method="ZALOPAY"), follow=False)
bid2 = int(r.headers["Location"].split("/booking/")[1].split("/")[0])
cu.post(f"/booking/{bid2}/pay", dict(result="ok"))
check("thanh toán xong -> UPCOMING (qua on_paid)", db("SELECT status FROM bookings WHERE booking_id=?", (bid2,))[0]["status"] == "UPCOMING")
r = cu.post(f"/booking/{bid2}/cancel", {})
check("đơn UPCOMING hủy được -> CANCELLED",
      db("SELECT status FROM bookings WHERE booking_id=?", (bid2,))[0]["status"] == "CANCELLED", text(r)[:200])

print(f"\n==== STATE: {len(PASS)} đạt, {len(FAIL)} lỗi ====")
sys.exit(1 if FAIL else 0)
