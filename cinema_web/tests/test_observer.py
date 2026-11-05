"""Kiểm thử mẫu Observer (cinema/events.py, cinema/observers.py):  python tests/test_observer.py"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import Client, make_app  # noqa: E402

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


from cinema import events, observers  # noqa: E402
from cinema.events import Subject, Observer, BookingPaid, booking_paid  # noqa: E402

# ---------- đơn vị: Subject ----------
log = []


class Spy(Observer):
    def __init__(self, name, boom=False):
        self.name, self.boom = name, boom

    def update(self, event):
        log.append(self.name)
        if self.boom:
            raise RuntimeError("lỗi cố ý")


s = Subject()
a, b = Spy("A"), Spy("B")
s.attach(a)
s.attach(b)
s.attach(a)
check("attach trùng observer bị bỏ qua", len(s.observers) == 2)
s.notify(object())
check("notify gọi theo thứ tự đăng ký", log == ["A", "B"])
log.clear()
s.detach(a)
s.notify(object())
check("detach xong thì observer không còn được gọi", log == ["B"])
log.clear()
s.clear()
s.attach(Spy("X", boom=True))
s.attach(Spy("Y"))
try:
    s.notify(object())
    check("lỗi trong observer được ném lên (để hoàn tác giao dịch)", False)
except RuntimeError:
    check("lỗi trong observer được ném lên (để hoàn tác giao dịch)", log == ["X"])

# ---------- observer mặc định ----------
names = [type(o).__name__ for o in booking_paid.observers]
check("5 observer mặc định đúng thứ tự",
      names == ["IssueQrObserver", "StockObserver", "LoyaltyObserver", "InAppNotificationObserver", "EmailObserver"], names)
observers.register_default_observers()
observers.register_default_observers()
check("đăng ký nhiều lần không bị nhân đôi", len(booking_paid.observers) == 5)

# ---------- tích hợp: thanh toán thật -> observer chạy ----------
received = []


class EventSpy(Observer):
    def update(self, event):
        received.append(event)


booking_paid.attach(EventSpy())

cu = Client(app)
cu.login("khach@cinema.vn")
with app.app_context():
    from cinema import services as sv
    seats = [s_ for s_ in sv.seat_map(1, None) if s_["status"] == "AVAILABLE"][:2]
r = cu.post_json("/api/cart/hold", dict(showtime_id=1, mode="online",
                                        seats=[dict(seat_id=s_["seat_id"], ticket_type_id=1) for s_ in seats]))
check("giữ 2 ghế", r.status_code == 200 and r.get_json()["ok"])
cu.post("/booking/combo", {})
r = cu.post("/booking/checkout", dict(method="MOMO"), follow=False)
bid = int(r.headers["Location"].split("/booking/")[1].split("/")[0])
pts_before = db("SELECT total_points p FROM customers WHERE customer_id=1")[0]["p"]
notif_before = db("SELECT COUNT(*) n FROM notifications")[0]["n"]
check("trước khi thanh toán chưa có sự kiện", received == [])
r = cu.post(f"/booking/{bid}/pay", dict(result="ok"))
check("thanh toán xong -> đúng 1 sự kiện BookingPaid", len(received) == 1 and isinstance(received[0], BookingPaid), received)
ev = received[0] if received else None
check("sự kiện mang đúng đơn / phương thức / số vé",
      ev and ev.booking["booking_id"] == bid and ev.method == "MOMO" and len(ev.tickets) == 2)
bk = db("SELECT * FROM bookings WHERE booking_id=?", (bid,))[0]
check("đơn UPCOMING + PAID", bk["status"] == "UPCOMING" and bk["payment_status"] == "PAID")
check("IssueQrObserver: vé có QR", all(t["qr_code"] for t in db("SELECT * FROM tickets WHERE booking_id=?", (bid,))))
pts_after = db("SELECT total_points p FROM customers WHERE customer_id=1")[0]["p"]
check("LoyaltyObserver: điểm tăng đúng và ghi vào đơn",
      pts_after - pts_before == bk["total_amount"] // 10000 == bk["points_earned"], (pts_before, pts_after, bk))
check("InAppNotificationObserver: có thông báo mới",
      db("SELECT COUNT(*) n FROM notifications")[0]["n"] == notif_before + 1)

# thanh toán lần 2 (đã PAID) không phát thêm sự kiện
with app.app_context():
    from cinema import services as sv
    sv.finalize_paid(bid, "MOMO")
    from cinema import db as dbm
    dbm.commit()
check("đơn đã thanh toán, gọi lại -> không phát thêm sự kiện", len(received) == 1)

# thêm observer mới KHÔNG cần sửa finalize_paid
extra = []


class Extra(Observer):
    def update(self, event):
        extra.append(event.booking["booking_code"])


booking_paid.attach(Extra())
with app.app_context():
    from cinema import services as sv
    seats2 = [s_ for s_ in sv.seat_map(1, None) if s_["status"] == "AVAILABLE"][:1]
r = cu.post_json("/api/cart/hold", dict(showtime_id=1, mode="online", seats=[dict(seat_id=x["seat_id"], ticket_type_id=1)
                                                                              for x in seats2]))
check("giữ thêm 1 ghế cho đơn thứ hai", r.status_code == 200 and r.get_json()["ok"])
cu.post("/booking/combo", {})
r = cu.post("/booking/checkout", dict(method="VNPAY"), follow=False)
bid2 = int(r.headers["Location"].split("/booking/")[1].split("/")[0])
cu.post(f"/booking/{bid2}/pay", dict(result="ok"))
check("observer mới (Extra) tự được gọi sau thanh toán", len(extra) == 1 and len(received) == 2)

print(f"\n==== OBSERVER: {len(PASS)} đạt, {len(FAIL)} lỗi ====")
sys.exit(1 if FAIL else 0)
