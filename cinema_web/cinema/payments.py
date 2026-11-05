"""MẪU STRATEGY (+ Factory đơn giản) - phương thức thanh toán (UC35, UC38).

Mỗi phương thức thanh toán là một chiến lược (cùng giao diện PaymentStrategy) quyết định:
  - giữ ghế thế nào khi vừa tạo đơn          -> reserve_seats()
  - khi nào đơn chưa thanh toán bị hủy       -> expiry_reason()
  - có phải thanh toán tại quầy hay không     -> pay_at_counter

    CashPayment      - tiền mặt tại quầy: ghế được giữ (SOLD) đến trước giờ chiếu
    GatewayPayment   - cổng thanh toán online (MoMo, ZaloPay, VNPay, Thẻ): ghế chỉ giữ tạm,
                       mất ghế thì đơn bị hủy

get_payment()/find_payment() là hàm tạo (Factory): từ mã phương thức trả về đúng chiến lược.
Thêm ví điện tử mới = thêm 1 lớp con + 1 dòng đăng ký, các view / services không phải sửa.
"""
from abc import ABC, abstractmethod

from .db import run, in_clause


class PaymentStrategy(ABC):
    code = ""
    label = ""
    pay_at_counter = False

    @abstractmethod
    def reserve_seats(self, showtime_id, seat_ids):
        """Gọi ngay sau khi tạo đơn."""

    @abstractmethod
    def expiry_reason(self, seat_statuses, showtime_start, at):
        """Trả về lý do hủy đơn chưa thanh toán (chuỗi) hoặc None nếu đơn vẫn còn hiệu lực."""


class CashPayment(PaymentStrategy):
    code = "CASH"
    label = "Tiền mặt tại quầy"
    pay_at_counter = True

    def reserve_seats(self, showtime_id, seat_ids):
        # giữ chỗ đến trước giờ chiếu (UC35 luồng thay thế 8a)
        run("UPDATE showtime_seats SET status='SOLD', held_by=NULL, held_until=NULL WHERE showtime_id=%s AND seat_id IN ("
            + in_clause(seat_ids) + ")", (showtime_id, *seat_ids))

    def expiry_reason(self, seat_statuses, showtime_start, at):
        if showtime_start and showtime_start < at:
            return "Quá giờ chiếu mà chưa thanh toán"
        return None


class GatewayPayment(PaymentStrategy):
    """Thanh toán online qua cổng (giả lập)."""

    def reserve_seats(self, showtime_id, seat_ids):
        pass  # giữ ghế tạm thời (HELD), chỉ SOLD sau khi thanh toán thành công

    def expiry_reason(self, seat_statuses, showtime_start, at):
        if any(s != "HELD" for s in seat_statuses):
            return "Hết thời gian giữ chỗ"
        return None


class MomoPayment(GatewayPayment):
    code, label = "MOMO", "Ví MoMo"


class ZaloPayPayment(GatewayPayment):
    code, label = "ZALOPAY", "ZaloPay"


class VnPayPayment(GatewayPayment):
    code, label = "VNPAY", "VNPay"


class CardPayment(GatewayPayment):
    code, label = "CARD", "Thẻ ngân hàng / Visa"


_REGISTRY = {s.code: s for s in (MomoPayment(), ZaloPayPayment(), VnPayPayment(), CardPayment(), CashPayment())}


def find_payment(code):
    """Trả về chiến lược theo mã, hoặc None nếu mã không hợp lệ."""
    return _REGISTRY.get(code)


def get_payment(code):
    from .services import AppError
    s = find_payment(code)
    if s is None:
        raise AppError("Phương thức thanh toán không hợp lệ")
    return s


def online_methods():
    """{mã: nhãn} của các phương thức qua cổng online (dùng cho giao diện chọn thanh toán)."""
    return {s.code: s.label for s in _REGISTRY.values() if not s.pay_at_counter}
