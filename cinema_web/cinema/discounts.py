"""MẪU STRATEGY - tính mức giảm giá (UC38, UC46).

Mỗi quy tắc giảm giá là một chiến lược riêng (cùng giao diện DiscountStrategy):
    TierDiscount       - ưu đãi theo hạng thành viên
    PromotionDiscount  - các chương trình khuyến mãi đang chạy (ngày ưu đãi, sinh viên, ...)
DiscountCalculator (Context) chạy lần lượt các chiến lược và lấy mức giảm CAO NHẤT,
không cộng dồn - đúng công thức:  Đơn giá = Giá vé - (KM x Giá vé).

Thêm loại giảm giá mới = viết thêm 1 lớp con DiscountStrategy rồi đưa vào danh sách,
không phải sửa code đang chạy (nguyên tắc Open/Closed).
"""
from abc import ABC, abstractmethod
from typing import NamedTuple, Optional

from .db import q, q1


class Discount(NamedTuple):
    """Kết quả của một chiến lược: (phần trăm, id khuyến mãi hoặc None, nhãn hiển thị)."""
    percent: float
    promo_id: Optional[int]
    label: str


NO_DISCOUNT = Discount(0.0, None, "")


class DiscountContext:
    """Dữ liệu dùng chung cho các chiến lược trong một lần tính (tránh truy vấn hạng thành viên nhiều lần)."""

    def __init__(self, customer, start_dt):
        self.customer = customer
        self.start_dt = start_dt
        self._tier = None
        self._tier_loaded = False

    @property
    def tier(self):
        if not self._tier_loaded:
            self._tier = q1("SELECT * FROM membership_tiers WHERE tier_id=%s", (self.customer["tier_id"],))
            self._tier_loaded = True
        return self._tier

    @property
    def member_points(self):
        return self.tier["min_points"] if self.tier else 0


class DiscountStrategy(ABC):
    """Strategy: giao diện chung của mọi quy tắc giảm giá."""

    @abstractmethod
    def candidates(self, ctx):
        """Trả về danh sách Discount mà quy tắc này áp dụng được cho khách hàng / suất chiếu."""


class TierDiscount(DiscountStrategy):
    """Ưu đãi theo hạng thành viên."""

    def candidates(self, ctx):
        tier = ctx.tier
        if tier and float(tier["discount_percent"]) > 0:
            return [Discount(float(tier["discount_percent"]), None, f"Hạng {tier['tier_name']}")]
        return []


class PromotionDiscount(DiscountStrategy):
    """Khuyến mãi đang chạy: đúng ngày trong tuần, đủ điểm hạng tối thiểu, loại STUDENT chỉ dành cho sinh viên."""

    def candidates(self, ctx):
        d = ctx.start_dt.date()
        rows = q("SELECT p.*, COALESCE(t.min_points,0) AS need_points FROM promotions p "
                 "LEFT JOIN membership_tiers t ON t.tier_id=p.min_tier_id "
                 "WHERE p.is_active=1 AND p.start_date<=%s AND p.end_date>=%s", (d, d))
        out = []
        for p in rows:
            if p["day_of_week"] is not None and int(p["day_of_week"]) != ctx.start_dt.isoweekday():
                continue
            if p["promo_type"] == "STUDENT" and not ctx.customer["is_student"]:
                continue
            if int(p["need_points"]) > int(ctx.member_points):
                continue
            out.append(Discount(float(p["discount_percent"]), p["promotion_id"], p["name"]))
        return out


class DiscountCalculator:
    """Context: giữ danh sách chiến lược và chọn mức giảm cao nhất (gặp mức bằng nhau thì giữ cái đến trước)."""

    def __init__(self, strategies):
        self.strategies = list(strategies)

    def best(self, customer, start_dt):
        best = NO_DISCOUNT
        if not customer:
            return best
        ctx = DiscountContext(customer, start_dt)
        for strategy in self.strategies:
            for cand in strategy.candidates(ctx):
                if cand.percent > best.percent:
                    best = cand
        return best


DEFAULT_CALCULATOR = DiscountCalculator([TierDiscount(), PromotionDiscount()])


def best_discount(customer, start_dt):
    return DEFAULT_CALCULATOR.best(customer, start_dt)
