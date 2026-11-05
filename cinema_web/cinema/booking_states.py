"""MẪU STATE - vòng đời của đơn đặt vé (UC35, UC40, UC48).

    PENDING_CONFIRM --thanh toán--> UPCOMING --(đến giờ chiếu)--> IN_PROGRESS --> COMPLETED
          |                            |
          +-------- hủy hết vé --------+--------> CANCELLED

Mỗi trạng thái là một lớp (cùng giao diện BookingState) tự quyết định:
  - đơn có được đổi / hủy vé không           -> can_change, require_changeable()
  - thanh toán xong thì chuyển sang đâu       -> on_paid()
  - hủy hết vé thì chuyển sang đâu            -> on_all_tickets_cancelled()
Nhờ đó không còn những câu so sánh chuỗi rải rác như  status in ('UPCOMING', 'PENDING_CONFIRM')
trong views / services; thêm trạng thái mới chỉ cần thêm một lớp.

Lưu ý: CSDL chỉ lưu PENDING_CONFIRM / UPCOMING / CANCELLED; IN_PROGRESS và COMPLETED là trạng thái HIỂN THỊ
được suy ra theo giờ chiếu (display_state) để người dùng thấy ở tab "Vé của tôi".
"""
from abc import ABC


class BookingState(ABC):
    code = ""
    label = ""
    can_change = False      # được phép đổi / hủy vé (còn phải thỏa điều kiện thời gian ở change_allowed)

    def on_paid(self):
        """Trạng thái kế tiếp khi thanh toán thành công."""
        return UPCOMING

    def on_all_tickets_cancelled(self):
        """Trạng thái kế tiếp khi mọi vé trong đơn đã bị hủy."""
        return CANCELLED

    def require_changeable(self, action):
        """Ném AppError nếu trạng thái này không cho phép đổi / hủy ('hủy', 'đổi vé')."""
        if not self.can_change:
            from .services import AppError
            raise AppError(f"Đơn hàng này không thể {action}")

    def __repr__(self):
        return f"<{type(self).__name__} {self.code}>"


class PendingConfirmState(BookingState):
    code, label, can_change = "PENDING_CONFIRM", "Chờ xác nhận", True


class UpcomingState(BookingState):
    code, label, can_change = "UPCOMING", "Sắp tới", True


class InProgressState(BookingState):
    code, label = "IN_PROGRESS", "Đang thực hiện"


class CompletedState(BookingState):
    code, label = "COMPLETED", "Đã hoàn tất"


class CancelledState(BookingState):
    code, label = "CANCELLED", "Đã hủy"

    def on_paid(self):
        from .services import AppError
        raise AppError("Đơn hàng đã bị hủy")


# Các trạng thái không có dữ liệu riêng nên dùng chung một đối tượng (Flyweight)
PENDING_CONFIRM = PendingConfirmState()
UPCOMING = UpcomingState()
IN_PROGRESS = InProgressState()
COMPLETED = CompletedState()
CANCELLED = CancelledState()

ALL = (PENDING_CONFIRM, UPCOMING, IN_PROGRESS, COMPLETED, CANCELLED)
_BY_CODE = {s.code: s for s in ALL}
LABELS = {s.code: s.label for s in ALL}


def state_of(code):
    """Từ mã lưu trong CSDL (bookings.status) lấy đối tượng trạng thái."""
    return _BY_CODE[code]


def display_state(status, start_dt, end_dt, at):
    """Trạng thái hiển thị: đơn đã thanh toán (UPCOMING) tự chuyển IN_PROGRESS / COMPLETED theo giờ chiếu."""
    if status in (CANCELLED.code, PENDING_CONFIRM.code):
        return state_of(status)
    return UPCOMING if at < start_dt else (IN_PROGRESS if at <= end_dt else COMPLETED)
