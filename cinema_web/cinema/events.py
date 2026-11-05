"""MẪU OBSERVER - sự kiện "đơn đặt vé đã thanh toán thành công" (UC39, UC44, UC45).

Subject  : Subject         - giữ danh sách observer, gọi notify(event) để báo cho tất cả
Observer : Observer        - giao diện update(event); các observer cụ thể nằm ở observers.py
Event    : BookingPaid     - dữ liệu của sự kiện (đơn, phương thức, mã giao dịch, danh sách vé...)

finalize_paid() chỉ cập nhật trạng thái đơn rồi phát sự kiện; việc xuất QR, trừ kho, tích điểm,
thông báo, gửi email do từng observer tự đảm nhận. Thêm một việc mới sau khi thanh toán
= viết thêm một observer, không phải sửa finalize_paid().
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class Observer(ABC):
    @abstractmethod
    def update(self, event):
        """Được Subject gọi khi có sự kiện."""


class Subject:
    def __init__(self):
        self._observers = []

    def attach(self, observer):
        if observer not in self._observers:
            self._observers.append(observer)

    def detach(self, observer):
        if observer in self._observers:
            self._observers.remove(observer)

    def clear(self):
        self._observers.clear()

    @property
    def observers(self):
        return tuple(self._observers)

    def notify(self, event):
        # Chạy theo thứ tự đăng ký. Lỗi nghiệp vụ (vd hết hàng) được ném lên để cả giao dịch bị hoàn tác.
        for observer in list(self._observers):
            observer.update(event)


@dataclass
class BookingPaid:
    """Sự kiện: đơn đã thanh toán thành công."""
    booking: dict                 # dòng bookings (đã khóa FOR UPDATE)
    method: str
    emp_id: int = None
    txn_ref: str = None
    paid_at: object = None
    tickets: list = field(default_factory=list)   # các vé VALID của đơn


# Subject dùng chung cho toàn ứng dụng; observer mặc định được đăng ký ở observers.register_default_observers()
booking_paid = Subject()
