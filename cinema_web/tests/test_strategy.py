"""Kiểm thử mẫu Strategy (cinema/discounts.py, cinema/payments.py):  python tests/test_strategy.py
Đối chiếu kết quả với bản cài đặt GỐC của best_discount (chép lại bên dưới) trên dữ liệu mẫu."""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import make_app  # noqa: E402

app, DB, skipped = make_app()
PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(("  ok   " if cond else "  LOI  ") + name)


def original_best_discount(customer, start_dt):
    """Bản gốc (trước khi refactor sang Strategy) - dùng làm chuẩn đối chiếu."""
    from cinema.db import q, q1
    best = (0.0, None, "")
    if not customer:
        return best
    tier = q1("SELECT * FROM membership_tiers WHERE tier_id=%s", (customer["tier_id"],))
    if tier and float(tier["discount_percent"]) > 0:
        best = (float(tier["discount_percent"]), None, f"Hạng {tier['tier_name']}")
    d = start_dt.date()
    rows = q("SELECT p.*, COALESCE(t.min_points,0) AS need_points FROM promotions p "
             "LEFT JOIN membership_tiers t ON t.tier_id=p.min_tier_id "
             "WHERE p.is_active=1 AND p.start_date<=%s AND p.end_date>=%s", (d, d))
    my_pts = tier["min_points"] if tier else 0
    for p in rows:
        if p["day_of_week"] is not None and int(p["day_of_week"]) != start_dt.isoweekday():
            continue
        if p["promo_type"] == "STUDENT" and not customer["is_student"]:
            continue
        if int(p["need_points"]) > int(my_pts):
            continue
        pct = float(p["discount_percent"])
        if pct > best[0]:
            best = (pct, p["promotion_id"], p["name"])
    return best


with app.app_context():
    from cinema import services as sv, discounts, payments
    from cinema.db import q, run, ex
    from cinema.payments import PaymentStrategy

    # ---------------- Strategy giảm giá ----------------
    check("không có khách -> không giảm", tuple(sv.best_discount(None, datetime.now())) == (0.0, None, ""))
    customers = q("SELECT * FROM customers")
    tiers = q("SELECT * FROM membership_tiers")
    # thêm vài khách giả định để phủ nhiều hạng / sinh viên / không phải sinh viên
    variants = []
    for c in customers:
        for t in tiers:
            for stu in (0, 1):
                variants.append(dict(c, tier_id=t["tier_id"], is_student=stu))
    base = datetime.now().replace(hour=19, minute=0, second=0, microsecond=0)
    times = [base + timedelta(days=i, hours=h) for i in range(0, 8) for h in (-8, 0, 3)]
    same, total = 0, 0
    for c in variants:
        for t in times:
            total += 1
            if tuple(sv.best_discount(c, t)) == original_best_discount(c, t):
                same += 1
    check(f"best_discount == bản gốc trên {total} tổ hợp (khách x hạng x ngày giờ)", same == total and total > 0)
    check("kết quả vẫn giải nén được thành 3 giá trị", len(tuple(sv.best_discount(variants[0], base))) == 3)

    # strategy mới cắm thêm vào được mà không sửa code cũ
    class FlatTen(discounts.DiscountStrategy):
        def candidates(self, ctx):
            return [discounts.Discount(10.0, None, "Giảm đồng giá 10%")]

    calc = discounts.DiscountCalculator([discounts.TierDiscount(), discounts.PromotionDiscount(), FlatTen()])
    got = calc.best(variants[0], base)
    check("thêm chiến lược mới (FlatTen) không cần sửa code cũ", got.percent >= 10.0)
    only = discounts.DiscountCalculator([FlatTen()])
    check("Calculator chỉ dùng chiến lược được đưa vào", only.best(variants[0], base).label == "Giảm đồng giá 10%")
    check("không có khách thì mọi chiến lược bị bỏ qua", only.best(None, base) == discounts.NO_DISCOUNT)

    # ---------------- Strategy thanh toán ----------------
    check("online_methods đúng 4 cổng, đúng thứ tự và nhãn",
          list(payments.online_methods().items()) == [("MOMO", "Ví MoMo"), ("ZALOPAY", "ZaloPay"), ("VNPAY", "VNPay"),
                                                      ("CARD", "Thẻ ngân hàng / Visa")])
    check("CASH không nằm trong danh sách online", "CASH" not in payments.online_methods())
    check("find_payment mã lạ -> None", payments.find_payment("BITCOIN") is None)
    try:
        payments.get_payment("BITCOIN")
        check("get_payment mã lạ -> AppError", False)
    except sv.AppError:
        check("get_payment mã lạ -> AppError", True)
    check("mọi phương thức là một PaymentStrategy",
          all(isinstance(payments.get_payment(c), PaymentStrategy) for c in ("CASH", "MOMO", "ZALOPAY", "VNPAY", "CARD")))
    check("chỉ CASH là thanh toán tại quầy",
          [c for c in ("CASH", "MOMO", "ZALOPAY", "VNPAY", "CARD") if payments.get_payment(c).pay_at_counter] == ["CASH"])
    now = datetime.now()
    cash, momo = payments.get_payment("CASH"), payments.get_payment("MOMO")
    check("CASH: chưa tới giờ chiếu -> còn hiệu lực", cash.expiry_reason(["SOLD"], now + timedelta(hours=1), now) is None)
    check("CASH: quá giờ chiếu -> hủy", cash.expiry_reason(["SOLD"], now - timedelta(minutes=1), now) == "Quá giờ chiếu mà chưa thanh toán")
    check("CASH: ghế bị nhả (không còn HELD) vẫn không hủy (ghế đã SOLD giữ chỗ)",
          cash.expiry_reason(["AVAILABLE"], now + timedelta(hours=1), now) is None)
    check("MOMO: ghế còn HELD -> còn hiệu lực", momo.expiry_reason(["HELD", "HELD"], now + timedelta(hours=1), now) is None)
    check("MOMO: mất ghế -> hủy", momo.expiry_reason(["HELD", "AVAILABLE"], now + timedelta(hours=1), now) == "Hết thời gian giữ chỗ")

print(f"\n==== STRATEGY: {len(PASS)} đạt, {len(FAIL)} lỗi ====")
sys.exit(1 if FAIL else 0)
