-- Dữ liệu mẫu để chạy thử web. Mật khẩu tất cả tài khoản mẫu: Admin@123
USE cinema_booking;

INSERT INTO roles (role_code, role_name) VALUES
 ('CUSTOMER','Khách hàng'),('TICKET_STAFF','Nhân viên bán vé / quầy'),
 ('WAREHOUSE_STAFF','Nhân viên kho / F&B'),('MANAGER','Quản lý rạp'),('ADMIN','Admin hệ thống');

INSERT INTO membership_tiers (tier_name, min_points, discount_percent) VALUES
 ('Thường',0,0),('Bạc',200,3),('Vàng',500,5),('Kim cương',1000,10);

INSERT INTO seat_types (type_name, surcharge, seat_capacity) VALUES
 ('Standard',0,1),('VIP',20000,1),('Sweetbox',40000,2),('Ghế đôi',30000,2);

INSERT INTO shifts (shift_name, start_time, end_time, max_staff) VALUES
 ('Ca sáng','08:00:00','13:00:00',5),('Ca chiều','13:00:00','18:00:00',5),('Ca tối','18:00:00','23:00:00',6);

INSERT INTO system_settings (setting_key, setting_value, description) VALUES
 ('HOLD_SECONDS','300','Thời gian giữ ghế tạm thời (5 phút)'),
 ('MAX_SEATS_PER_BOOKING','10','Số ghế tối đa mỗi đơn'),
 ('POINT_DIVISOR','10000','Điểm = tổng tiền / 10.000'),
 ('LATE_THRESHOLD_MIN','15','Ngưỡng đến muộn bị tính vi phạm (phút)'),
 ('NEAR_EXPIRY_DAYS','7','Số ngày cảnh báo cận hạn'),
 ('CANCEL_BEFORE_MIN','120','Chỉ đổi/hủy vé trước giờ chiếu tối thiểu (phút)'),
 ('OTP_SECONDS','180','Thời gian hiệu lực OTP');

-- Tài khoản mẫu (cùng mật khẩu Admin@123)
SET @pw = 'scrypt:32768:8:1$HgkQbqcRIrWZH8me$08b214ed0276b8afcfb156e158c3904209138a3a150817cea907be2e496bc33137e46a19a88ff10f199f3337aa848a77f4e997a629f77c322b90525da94d45e2';
INSERT INTO users (role_id, email, password_hash, full_name, phone) VALUES
 (5,'admin@cinema.vn',@pw,'Quản trị viên','0900000001'),
 (4,'quanly@cinema.vn',@pw,'Nguyễn Quản Lý','0900000002'),
 (2,'banve@cinema.vn',@pw,'Lê Bán Vé','0900000003'),
 (3,'kho@cinema.vn',@pw,'Trần Kho','0900000004'),
 (1,'khach@cinema.vn',@pw,'Phạm Khách Hàng','0900000005'),
 (1,'danh@cinema.vn',@pw,'Nguyen Ngoc Danh','0900000006');
INSERT INTO customers (user_id, tier_id) VALUES (5,1),(6,1);
INSERT INTO employees (user_id, position, employment_type, hourly_wage, hire_date) VALUES
 (2,'Quản lý rạp','FULL_TIME',60000,'2025-01-01'),
 (3,'Nhân viên bán vé','PART_TIME',30000,'2025-06-01'),
 (4,'Nhân viên kho','PART_TIME',30000,'2025-06-01');

INSERT INTO genres (genre_name) VALUES ('Hành động'),('Tình cảm'),('Hoạt hình'),('Kinh dị'),('Hài');
INSERT INTO distributors (name) VALUES ('Nhà phát hành A'),('Nhà phát hành B');

INSERT INTO movies (title, release_year, age_rating, duration_min, director, cast_list, description, release_date, status) VALUES
 ('Phim Hành Động 1',2026,'T16',120,'Đạo diễn A','Diễn viên 1, Diễn viên 2','Mô tả phim mẫu 1','2026-10-01','NOW_SHOWING'),
 ('Phim Hoạt Hình 2',2026,'P',95,'Đạo diễn B','Diễn viên 3','Mô tả phim mẫu 2','2026-10-10','NOW_SHOWING'),
 ('Phim Kinh Dị 3',2026,'T18',105,'Đạo diễn C','Diễn viên 4, Diễn viên 5','Mô tả phim mẫu 3','2026-11-15','COMING_SOON');
INSERT INTO movie_genres VALUES (1,1),(2,3),(2,5),(3,4);
INSERT INTO distributor_contracts (movie_id, distributor_id, share_percent) VALUES (1,1,45),(2,2,40),(3,1,45);

INSERT INTO cinemas (name, address, city, phone) VALUES ('Rạp Trung Tâm','1 Võ Văn Ngân, Thủ Đức','TP.HCM','0280000000');
INSERT INTO rooms (cinema_id, room_name, room_type, capacity) VALUES (1,'Phòng 1','2D',40),(1,'Phòng 2','3D',40);

-- Sinh ghế: hàng A-E x 8 ghế. Hàng E là ghế đôi, hàng D là VIP, còn lại Standard
INSERT INTO seats (room_id, seat_type_id, row_label, seat_number)
SELECT r.room_id,
       CASE x.row_label WHEN 'E' THEN 4 WHEN 'D' THEN 2 ELSE 1 END,
       x.row_label, n.num
FROM rooms r
CROSS JOIN (SELECT 'A' row_label UNION SELECT 'B' UNION SELECT 'C' UNION SELECT 'D' UNION SELECT 'E') x
CROSS JOIN (SELECT 1 num UNION SELECT 2 UNION SELECT 3 UNION SELECT 4 UNION SELECT 5 UNION SELECT 6 UNION SELECT 7 UNION SELECT 8) n;

INSERT INTO schedules (cinema_id, title, period_type, start_date, end_date, created_by)
VALUES (1,'Lịch chiếu mẫu (2 tuần từ hôm nay)','WEEK',CURDATE(),DATE_ADD(CURDATE(), INTERVAL 13 DAY),2);
-- Suất chiếu mẫu tính theo ngày chạy seed (ngày mai, ngày kia...) để luôn còn hiệu lực
INSERT INTO showtimes (schedule_id, movie_id, room_id, start_time, end_time) VALUES
 (1,1,1,TIMESTAMP(DATE_ADD(CURDATE(), INTERVAL 1 DAY),'18:00:00'),TIMESTAMP(DATE_ADD(CURDATE(), INTERVAL 1 DAY),'20:15:00')),
 (1,2,2,TIMESTAMP(DATE_ADD(CURDATE(), INTERVAL 1 DAY),'19:00:00'),TIMESTAMP(DATE_ADD(CURDATE(), INTERVAL 1 DAY),'20:50:00')),
 (1,1,1,TIMESTAMP(DATE_ADD(CURDATE(), INTERVAL 2 DAY),'18:00:00'),TIMESTAMP(DATE_ADD(CURDATE(), INTERVAL 2 DAY),'20:15:00')),
 (1,2,2,TIMESTAMP(DATE_ADD(CURDATE(), INTERVAL 2 DAY),'19:00:00'),TIMESTAMP(DATE_ADD(CURDATE(), INTERVAL 2 DAY),'20:50:00')),
 (1,1,1,TIMESTAMP(DATE_ADD(CURDATE(), INTERVAL 3 DAY),'20:30:00'),TIMESTAMP(DATE_ADD(CURDATE(), INTERVAL 3 DAY),'22:45:00'));

-- Tạo trạng thái ghế cho từng suất
INSERT INTO showtime_seats (showtime_id, seat_id)
SELECT s.showtime_id, st.seat_id FROM showtimes s JOIN seats st ON st.room_id = s.room_id;

INSERT INTO ticket_types (type_name, room_type, base_price) VALUES
 ('Người lớn 2D','2D',90000),('Người lớn 3D','3D',120000),('Trẻ em 2D','2D',60000),('Sinh viên 2D','2D',65000);
INSERT INTO ticket_price_rules (ticket_type_id, day_of_week, time_from, time_to, price) VALUES
 (1,6,'00:00:00','23:59:59',100000),(1,7,'00:00:00','23:59:59',100000);

INSERT INTO promotions (name, promo_type, description, discount_percent, condition_text, day_of_week, start_date, end_date) VALUES
 ('C-Student','STUDENT','Giảm cho sinh viên',10,'Có thẻ sinh viên',NULL,'2026-01-01','2026-12-31'),
 ('C-Day thứ 4','SPECIAL_DAY','Ngày ưu đãi mỗi thứ 4',15,'Áp dụng thứ 4 hằng tuần',3,'2026-01-01','2026-12-31');

INSERT INTO fb_products (product_name, category, unit, price, is_combo) VALUES
 ('Bắp rang bơ (L)','POPCORN','hộp',55000,FALSE),
 ('Pepsi (L)','DRINK','ly',30000,FALSE),
 ('Combo 1 bắp + 1 nước','COMBO','combo',79000,TRUE);
INSERT INTO combo_components VALUES (3,1,1),(3,2,1);

INSERT INTO suppliers (name, phone) VALUES ('Công ty Nguyên liệu X','0281111111');
INSERT INTO stock_receipts (supplier_id, received_by, receipt_date) VALUES (1,3,CURDATE());
INSERT INTO inventory_batches (batch_code, receipt_id, product_id, qty_received, qty_remaining, import_date, expiry_date, unit_cost) VALUES
 ('LO-MAU-01',1,1,200,200,CURDATE(),DATE_ADD(CURDATE(), INTERVAL 5 DAY),20000),
 ('LO-MAU-02',1,2,300,300,CURDATE(),DATE_ADD(CURDATE(), INTERVAL 90 DAY),12000);

INSERT INTO qr_locations (qr_code, location_type, room_id, label) VALUES
 ('QR-LOBBY-01','LOBBY',NULL,'Sảnh chờ - bàn 1');

-- Tham số bổ sung (dữ liệu, không thêm bảng)
INSERT INTO system_settings (setting_key, setting_value, description) VALUES
 ('REFUND_PERCENT','100','Tỷ lệ hoàn tiền khi hủy vé hợp lệ (%)'),
 ('VIOLATION_FINE','0','Số tiền trừ lương cho mỗi lần vi phạm giờ giấc (VNĐ)');
