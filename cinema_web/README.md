# Hệ thống đặt vé xem phim - Nhóm 11 (Flask + MySQL)

Xây dựng theo báo cáo cuối kỳ: 14 module, 70 use case (UC01-UC70), 5 vai trò (Khách hàng, NV bán vé, NV kho, Quản lý rạp, Admin).
CSDL giữ nguyên 44 bảng trong `db/schema.sql`.

## 1. Chạy trên VS Code

```bash
# 1) Tạo môi trường ảo
python -m venv .venv
.venv\Scripts\activate            # Windows   (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt

# 2) Tạo CSDL: mở MySQL Workbench -> chạy lần lượt
#    db/schema.sql   (tạo database cinema_booking + 44 bảng)
#    db/seed.sql     (dữ liệu mẫu)

# 3) Cấu hình kết nối
copy .env.example .env            # sửa DB_PASSWORD cho đúng mật khẩu MySQL

# 4) Chạy
python app.py                     # mở http://127.0.0.1:5000
```

Tài khoản mẫu (mật khẩu chung `Admin@123`):

| Vai trò | Email |
|---|---|
| Admin | admin@cinema.vn |
| Quản lý rạp | quanly@cinema.vn |
| NV bán vé | banve@cinema.vn |
| NV kho | kho@cinema.vn |
| Khách hàng | khach@cinema.vn |

Khi chưa cấu hình email, mã OTP (đăng ký / quên mật khẩu) hiện ngay trên màn hình (`DEV_SHOW_OTP=1`) và in ra console.

## 2. Cấu trúc

```
app.py                  điểm chạy
cinema/__init__.py      tạo app, CSRF, phân quyền, job 00:00
cinema/mail.py          [Adapter]  gửi email: EmailSender / SmtpEmailSender / ConsoleEmailSender
cinema/discounts.py     [Strategy] quy tắc giảm giá: TierDiscount / PromotionDiscount + DiscountCalculator
cinema/payments.py      [Strategy] phương thức thanh toán: CashPayment / GatewayPayment (MoMo, ZaloPay, VNPay, Thẻ)
cinema/events.py        [Observer] Subject / Observer / sự kiện BookingPaid
cinema/observers.py     [Observer] xuất QR, trừ kho, tích điểm, thông báo, email sau khi thanh toán
cinema/booking_states.py [State]   vòng đời đơn đặt vé: PendingConfirm / Upcoming / InProgress / Completed / Cancelled
cinema/services.py      nghiệp vụ dùng chung: giữ ghế, giá vé, điểm, kho FIFO, hủy/hoàn
cinema/views/           auth · movies · cinema · pricing · booking · fnb · hr · reports · admin
cinema/templates/       giao diện Jinja2 + Bootstrap 5
cinema/static/js/       seat_picker.js (sơ đồ ghế), qr.js, countdown.js, suggest.js
db/schema.sql, seed.sql CSDL MySQL
tests/                  kiểm thử tự động (xem mục 4)
```

## 3. Các quy tắc nghiệp vụ đã cài

- Giữ ghế 5 phút (`HOLD_SECONDS`), hết hạn tự nhả; khóa dòng `showtime_seats` khi bán nên không bán trùng ghế.
- Đơn giá = (giá vé theo khung giờ + phụ thu ghế) - (% khuyến mãi x giá vé); lấy mức ưu đãi cao nhất (hạng thành viên / khuyến mãi).
- Điểm = tổng tiền / 10.000; hủy vé thu hồi điểm; hạng thành viên tự cập nhật.
- Trừ kho theo lô FIFO (ngày nhập, rồi hạn dùng); combo tự trừ theo thành phần; quét kho 00:00: cận hạn <= 7 ngày, hết hạn.
- Đổi/hủy vé chỉ trước giờ chiếu tối thiểu `CANCEL_BEFORE_MIN` (120 phút).
- Đến muộn > 15 phút (`LATE_THRESHOLD_MIN`) là vi phạm; quên check-out đánh dấu "Chưa hoàn tất".
- Tham số chỉnh trong Admin > Cấu hình hệ thống, không cần sửa code.

## 4. Kiểm thử

```bash
python tests/smoke.py        # mở mọi trang GET của 5 vai trò, báo lỗi 500
python tests/test_flows.py   # ~160 kiểm tra luồng nghiệp vụ
python tests/test_adapter.py # mẫu Adapter
python tests/test_strategy.py # mẫu Strategy
python tests/test_observer.py # mẫu Observer
python tests/test_state.py   # mẫu State
python tests/run_all.py      # chạy tất cả bộ kiểm thử
```

Hai file này chạy trên SQLite giả lập (`tests/sqlite_shim.py`) để kiểm tra logic khi không có MySQL; ứng dụng thật luôn dùng MySQL.

## 5. Mẫu thiết kế

Xem `docs/MAU_THIET_KE.md` (Adapter, Strategy, Observer, State: vấn đề, sơ đồ lớp, sơ đồ tuần tự).

## 6. Ghi chú

- Cổng thanh toán (MoMo/ZaloPay/VNPay/Thẻ) là **giả lập**: có nút "thành công / thất bại".
- Xuất báo cáo: CSV (mở bằng Excel) và In / Lưu PDF bằng trình duyệt.
- `db/seed.sql` tạo suất chiếu tính theo ngày chạy seed (ngày mai, ngày kia...) nên luôn còn hiệu lực.
