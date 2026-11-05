"""Các Observer cụ thể cho sự kiện BookingPaid. Thứ tự đăng ký = thứ tự thực hiện."""
import secrets

from .db import q, q1, run
from .events import Observer, booking_paid
from . import services as sv


class IssueQrObserver(Observer):
    """UC39: xuất mã QR cho từng vé."""

    def update(self, event):
        for t in event.tickets:
            run("UPDATE tickets SET qr_code=%s WHERE ticket_id=%s", (secrets.token_urlsafe(16), t["ticket_id"]))


class StockObserver(Observer):
    """UC44: trừ kho FIFO cho các món bắp nước / combo đã mua kèm."""

    def update(self, event):
        bid = event.booking["booking_id"]
        for it in q("SELECT * FROM booking_items WHERE booking_id=%s", (bid,)):
            sv.fifo_deduct(it["product_id"], int(it["quantity"]), booking_id=bid, emp_id=event.emp_id)


class LoyaltyObserver(Observer):
    """UC45: tích điểm thành viên và ghi số điểm vào đơn."""

    def update(self, event):
        b = event.booking
        pts = sv.add_points(b["customer_id"], b["total_amount"], b["booking_id"], f"Tích điểm đơn {b['booking_code']}")
        run("UPDATE bookings SET points_earned=%s WHERE booking_id=%s", (pts, b["booking_id"]))


def _customer_user(event):
    return q1("SELECT u.user_id, u.email, u.full_name FROM customers c JOIN users u ON u.user_id=c.user_id "
              "WHERE c.customer_id=%s", (event.booking["customer_id"],))


class InAppNotificationObserver(Observer):
    """Thông báo trong ứng dụng cho khách hàng."""

    def update(self, event):
        cu = _customer_user(event)
        sv.notify(cu["user_id"], f"Vé điện tử {event.booking['booking_code']}",
                  "Thanh toán thành công. Mở mục 'Vé của tôi' để xem mã QR.")


class EmailObserver(Observer):
    """Gửi email xác nhận (qua Adapter EmailSender) nếu khách có email."""

    def update(self, event):
        cu = _customer_user(event)
        code = event.booking["booking_code"]
        if cu["email"]:
            sv.send_mail(cu["email"], f"Vé xem phim {code}",
                         f"Xin chào {cu['full_name']}, đơn {code} đã thanh toán thành công. Đăng nhập để xem mã QR.")


def register_default_observers(subject=booking_paid):
    """Đăng ký bộ observer mặc định (gọi nhiều lần vẫn an toàn)."""
    subject.clear()
    for obs in (IssueQrObserver(), StockObserver(), LoyaltyObserver(), InAppNotificationObserver(), EmailObserver()):
        subject.attach(obs)
