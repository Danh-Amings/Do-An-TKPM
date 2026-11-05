-- =====================================================================
-- CSDL: HỆ THỐNG ĐẶT VÉ XEM PHIM - NHÓM 11
-- DBMS : MySQL 8.x (InnoDB, utf8mb4)
-- Nguồn: Báo cáo cuối kỳ - 14 module (QLP, QLTL, QLPC, QLGN, QLSC, QLLC,
--        QLLV, QLBV, QLKho, QLQR, QLSK, QLTV, QLNV, BCTK) + Đăng nhập + Admin
-- =====================================================================
DROP DATABASE IF EXISTS cinema_booking;
CREATE DATABASE cinema_booking CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE cinema_booking;

SET FOREIGN_KEY_CHECKS = 0;

-- =====================================================================
-- NHÓM 1. TÀI KHOẢN & PHÂN QUYỀN  (UC01-UC05, UC69)
-- =====================================================================
CREATE TABLE roles (
    role_id     TINYINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    role_code   VARCHAR(20)  NOT NULL UNIQUE,   -- CUSTOMER, TICKET_STAFF, WAREHOUSE_STAFF, MANAGER, ADMIN
    role_name   VARCHAR(60)  NOT NULL
) ENGINE=InnoDB;

CREATE TABLE users (
    user_id        INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    role_id        TINYINT UNSIGNED NOT NULL,
    email          VARCHAR(120) NULL UNIQUE,     -- NULL cho khách vãng lai tạo tại quầy
    password_hash  VARCHAR(255) NULL,            -- NULL cho khách vãng lai (chưa có tài khoản)
    full_name      VARCHAR(100) NOT NULL,
    phone          VARCHAR(15)  NULL UNIQUE,
    birth_date     DATE         NULL,
    gender         ENUM('M','F','OTHER') NULL,
    avatar_url     VARCHAR(255) NULL,            -- tối đa 5MB (kiểm tra ở tầng ứng dụng)
    status         ENUM('ACTIVE','LOCKED') NOT NULL DEFAULT 'ACTIVE',
    created_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_users_role FOREIGN KEY (role_id) REFERENCES roles(role_id)
) ENGINE=InnoDB;

CREATE TABLE otp_codes (                          -- UC02 đăng ký, UC03 quên mật khẩu (OTP 6 số, hết hạn 180s)
    otp_id      INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    email       VARCHAR(120) NOT NULL,
    purpose     ENUM('REGISTER','RESET_PASSWORD') NOT NULL,
    otp_hash    VARCHAR(255) NOT NULL,
    expires_at  DATETIME     NOT NULL,
    is_used     BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_otp_email (email, purpose)
) ENGINE=InnoDB;

CREATE TABLE system_settings (                    -- UC70 cấu hình tham số, không sửa mã nguồn
    setting_key   VARCHAR(60)  PRIMARY KEY,       -- vd: HOLD_SECONDS, MAX_SEATS_PER_BOOKING, POINT_DIVISOR,...
    setting_value VARCHAR(255) NOT NULL,
    description   VARCHAR(255) NULL,
    updated_by    INT UNSIGNED NULL,
    updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_settings_user FOREIGN KEY (updated_by) REFERENCES users(user_id)
) ENGINE=InnoDB;

CREATE TABLE notifications (                      -- thông báo cho khách/NV/quản lý (nhiều UC)
    notification_id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id     INT UNSIGNED NOT NULL,
    title       VARCHAR(150) NOT NULL,
    content     TEXT         NULL,
    is_read     BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_noti_user FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    INDEX idx_noti_user (user_id, is_read)
) ENGINE=InnoDB;

-- =====================================================================
-- NHÓM 2. THÀNH VIÊN & ĐIỂM THƯỞNG (QLTV: UC45-UC48)
-- =====================================================================
CREATE TABLE membership_tiers (
    tier_id           TINYINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    tier_name         VARCHAR(40)  NOT NULL UNIQUE,     -- Thường, Bạc, Vàng, Kim cương
    min_points        INT UNSIGNED NOT NULL DEFAULT 0,
    discount_percent  DECIMAL(5,2) NOT NULL DEFAULT 0,  -- % giảm theo hạng (UC46)
    CHECK (discount_percent BETWEEN 0 AND 100)
) ENGINE=InnoDB;

CREATE TABLE customers (
    customer_id  INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id      INT UNSIGNED NOT NULL UNIQUE,
    tier_id      TINYINT UNSIGNED NOT NULL DEFAULT 1,
    total_points INT UNSIGNED NOT NULL DEFAULT 0,
    is_student   BOOLEAN NOT NULL DEFAULT FALSE,        -- ưu đãi kiểu C'Student
    CONSTRAINT fk_cus_user FOREIGN KEY (user_id) REFERENCES users(user_id),
    CONSTRAINT fk_cus_tier FOREIGN KEY (tier_id) REFERENCES membership_tiers(tier_id)
) ENGINE=InnoDB;

-- =====================================================================
-- NHÓM 3. NHÂN VIÊN, CA LÀM, CHẤM CÔNG, LƯƠNG (QLNV: UC49-UC55)
-- =====================================================================
CREATE TABLE employees (
    employee_id      INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id          INT UNSIGNED NOT NULL UNIQUE,
    position         VARCHAR(60) NOT NULL,                       -- Chức vụ
    employment_type  ENUM('FULL_TIME','PART_TIME') NOT NULL DEFAULT 'PART_TIME',
    hourly_wage      DECIMAL(10,0) NOT NULL DEFAULT 0,
    hire_date        DATE NOT NULL,
    status           ENUM('WORKING','RESIGNED') NOT NULL DEFAULT 'WORKING',  -- "xóa" = nghỉ việc (xóa mềm)
    CONSTRAINT fk_emp_user FOREIGN KEY (user_id) REFERENCES users(user_id)
) ENGINE=InnoDB;

CREATE TABLE shifts (                                  -- ca mẫu: Sáng/Chiều/Tối
    shift_id    TINYINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    shift_name  VARCHAR(40) NOT NULL UNIQUE,
    start_time  TIME NOT NULL,
    end_time    TIME NOT NULL,
    max_staff   TINYINT UNSIGNED NOT NULL DEFAULT 5         -- "Ca đã đủ nhân viên"
) ENGINE=InnoDB;

CREATE TABLE shift_registrations (                     -- UC53
    registration_id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    employee_id     INT UNSIGNED NOT NULL,
    shift_id        TINYINT UNSIGNED NOT NULL,
    work_date       DATE NOT NULL,
    status          ENUM('PENDING','APPROVED','REJECTED') NOT NULL DEFAULT 'PENDING',
    approved_by     INT UNSIGNED NULL,                      -- employee_id của quản lý
    registered_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_reg (employee_id, shift_id, work_date),
    CONSTRAINT fk_reg_emp   FOREIGN KEY (employee_id) REFERENCES employees(employee_id),
    CONSTRAINT fk_reg_shift FOREIGN KEY (shift_id)    REFERENCES shifts(shift_id),
    CONSTRAINT fk_reg_appr  FOREIGN KEY (approved_by) REFERENCES employees(employee_id)
) ENGINE=InnoDB;

CREATE TABLE attendance (                              -- UC54: giờ lấy theo Server Time
    attendance_id   INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    registration_id INT UNSIGNED NOT NULL UNIQUE,
    check_in        DATETIME NULL,
    check_out       DATETIME NULL,
    late_minutes    SMALLINT UNSIGNED NOT NULL DEFAULT 0,
    is_violation    BOOLEAN NOT NULL DEFAULT FALSE,         -- đến muộn > 15 phút
    status          ENUM('IN_PROGRESS','COMPLETED','INCOMPLETE') NOT NULL DEFAULT 'IN_PROGRESS',
    CONSTRAINT fk_att_reg FOREIGN KEY (registration_id) REFERENCES shift_registrations(registration_id)
) ENGINE=InnoDB;

CREATE TABLE payslips (
    payslip_id    INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    employee_id   INT UNSIGNED NOT NULL,
    pay_month     TINYINT UNSIGNED NOT NULL,
    pay_year      SMALLINT UNSIGNED NOT NULL,
    total_hours   DECIMAL(6,2) NOT NULL DEFAULT 0,
    gross_amount  DECIMAL(12,0) NOT NULL DEFAULT 0,
    deduction     DECIMAL(12,0) NOT NULL DEFAULT 0,         -- trừ vi phạm giờ giấc
    net_amount    DECIMAL(12,0) NOT NULL DEFAULT 0,
    UNIQUE KEY uq_payslip (employee_id, pay_month, pay_year),
    CONSTRAINT fk_pay_emp FOREIGN KEY (employee_id) REFERENCES employees(employee_id)
) ENGINE=InnoDB;

CREATE TABLE salary_complaints (                       -- UC55
    complaint_id  INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    payslip_id    INT UNSIGNED NOT NULL,
    employee_id   INT UNSIGNED NOT NULL,
    content       TEXT NOT NULL,
    status        ENUM('PENDING','RESPONDED') NOT NULL DEFAULT 'PENDING',
    response      TEXT NULL,
    responded_by  INT UNSIGNED NULL,
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    responded_at  DATETIME NULL,
    CONSTRAINT fk_cmp_pay  FOREIGN KEY (payslip_id)   REFERENCES payslips(payslip_id),
    CONSTRAINT fk_cmp_emp  FOREIGN KEY (employee_id)  REFERENCES employees(employee_id),
    CONSTRAINT fk_cmp_resp FOREIGN KEY (responded_by) REFERENCES employees(employee_id)
) ENGINE=InnoDB;

-- =====================================================================
-- NHÓM 4. PHIM & THỂ LOẠI (QLP: UC06-UC11, QLTL: UC12-UC15)
-- =====================================================================
CREATE TABLE genres (
    genre_id    SMALLINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    genre_name  VARCHAR(60) NOT NULL UNIQUE
) ENGINE=InnoDB;

CREATE TABLE distributors (
    distributor_id  INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name            VARCHAR(120) NOT NULL UNIQUE,
    phone           VARCHAR(15) NULL,
    email           VARCHAR(120) NULL
) ENGINE=InnoDB;

CREATE TABLE movies (
    movie_id      INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    title         VARCHAR(200) NOT NULL,
    release_year  SMALLINT UNSIGNED NOT NULL,              -- "Năm SX"
    age_rating    ENUM('P','K','T13','T16','T18') NOT NULL DEFAULT 'P',   -- "Độ tuổi"
    duration_min  SMALLINT UNSIGNED NOT NULL,
    director      VARCHAR(120) NULL,
    cast_list     VARCHAR(500) NULL,                       -- diễn viên
    description   TEXT NULL,
    poster_url    VARCHAR(255) NULL,
    trailer_url   VARCHAR(255) NULL,
    release_date  DATE NULL,                               -- ngày khởi chiếu
    avg_rating    DECIMAL(3,1) NOT NULL DEFAULT 0,
    status        ENUM('COMING_SOON','NOW_SHOWING','STOPPED') NOT NULL DEFAULT 'COMING_SOON',
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_movie (title, release_year),             -- "Phim đã tồn tại"
    FULLTEXT KEY ft_movie (title, cast_list)               -- tìm kiếm gần đúng / theo diễn viên
) ENGINE=InnoDB;

CREATE TABLE movie_genres (                                -- N-N phim <-> thể loại
    movie_id  INT UNSIGNED NOT NULL,
    genre_id  SMALLINT UNSIGNED NOT NULL,
    PRIMARY KEY (movie_id, genre_id),
    CONSTRAINT fk_mg_movie FOREIGN KEY (movie_id) REFERENCES movies(movie_id) ON DELETE CASCADE,
    CONSTRAINT fk_mg_genre FOREIGN KEY (genre_id) REFERENCES genres(genre_id)   -- RESTRICT: không xóa thể loại đang có phim
) ENGINE=InnoDB;

CREATE TABLE distributor_contracts (                       -- UC61 chia sẻ doanh thu nhà phát hành
    contract_id     INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    movie_id        INT UNSIGNED NOT NULL,
    distributor_id  INT UNSIGNED NOT NULL,
    share_percent   DECIMAL(5,2) NOT NULL,                 -- % doanh thu trả cho nhà phát hành
    start_date      DATE NULL,
    end_date        DATE NULL,                             -- hết hạn quyền phát hành
    UNIQUE KEY uq_contract (movie_id, distributor_id),
    CONSTRAINT fk_ct_movie FOREIGN KEY (movie_id) REFERENCES movies(movie_id),
    CONSTRAINT fk_ct_dist  FOREIGN KEY (distributor_id) REFERENCES distributors(distributor_id),
    CHECK (share_percent BETWEEN 0 AND 100)
) ENGINE=InnoDB;

-- =====================================================================
-- NHÓM 5. RẠP, PHÒNG CHIẾU, GHẾ (QLPC: UC16-UC19, QLGN: UC20-UC22)
-- =====================================================================
CREATE TABLE cinemas (
    cinema_id  INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name       VARCHAR(120) NOT NULL,
    address    VARCHAR(255) NOT NULL,
    city       VARCHAR(60)  NOT NULL,
    phone      VARCHAR(15)  NULL
) ENGINE=InnoDB;

CREATE TABLE rooms (
    room_id     INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    cinema_id   INT UNSIGNED NOT NULL,
    room_name   VARCHAR(40) NOT NULL,
    room_type   ENUM('2D','3D','IMAX') NOT NULL DEFAULT '2D',
    capacity    SMALLINT UNSIGNED NOT NULL,
    status      ENUM('ACTIVE','INACTIVE') NOT NULL DEFAULT 'ACTIVE',   -- ngừng sử dụng khi bảo trì
    UNIQUE KEY uq_room (cinema_id, room_name),                         -- "Tên phòng đã tồn tại"
    CONSTRAINT fk_room_cinema FOREIGN KEY (cinema_id) REFERENCES cinemas(cinema_id)
) ENGINE=InnoDB;

CREATE TABLE seat_types (
    seat_type_id  TINYINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    type_name     VARCHAR(30) NOT NULL UNIQUE,            -- Standard / VIP / Sweetbox / Ghế đôi
    surcharge     DECIMAL(10,0) NOT NULL DEFAULT 0,       -- phụ thu theo loại ghế
    seat_capacity TINYINT UNSIGNED NOT NULL DEFAULT 1     -- ghế đôi = 2 chỗ
) ENGINE=InnoDB;

CREATE TABLE seats (
    seat_id       INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    room_id       INT UNSIGNED NOT NULL,
    seat_type_id  TINYINT UNSIGNED NOT NULL,
    row_label     CHAR(2) NOT NULL,                       -- A, B, C...
    seat_number   TINYINT UNSIGNED NOT NULL,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,          -- ghế hỏng = FALSE
    UNIQUE KEY uq_seat (room_id, row_label, seat_number),
    CONSTRAINT fk_seat_room FOREIGN KEY (room_id) REFERENCES rooms(room_id) ON DELETE CASCADE,
    CONSTRAINT fk_seat_type FOREIGN KEY (seat_type_id) REFERENCES seat_types(seat_type_id)
) ENGINE=InnoDB;

-- =====================================================================
-- NHÓM 6. LỊCH CHIẾU & SUẤT CHIẾU (QLLC: UC27-UC31, QLSC: UC23-UC26)
-- =====================================================================
CREATE TABLE schedules (                                   -- lịch chiếu tuần/tháng
    schedule_id  INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    cinema_id    INT UNSIGNED NOT NULL,
    title        VARCHAR(120) NOT NULL,
    period_type  ENUM('WEEK','MONTH') NOT NULL DEFAULT 'WEEK',
    start_date   DATE NOT NULL,
    end_date     DATE NOT NULL,
    created_by   INT UNSIGNED NOT NULL,                    -- users.user_id (quản lý)
    created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_sch_cinema FOREIGN KEY (cinema_id) REFERENCES cinemas(cinema_id),
    CONSTRAINT fk_sch_user   FOREIGN KEY (created_by) REFERENCES users(user_id),
    CHECK (end_date >= start_date)
) ENGINE=InnoDB;

CREATE TABLE showtimes (
    showtime_id  INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    schedule_id  INT UNSIGNED NOT NULL,
    movie_id     INT UNSIGNED NOT NULL,
    room_id      INT UNSIGNED NOT NULL,
    start_time   DATETIME NOT NULL,
    end_time     DATETIME NOT NULL,                        -- = start + duration + thời gian dọn phòng
    status       ENUM('SCHEDULED','CANCELLED','FINISHED') NOT NULL DEFAULT 'SCHEDULED',
    UNIQUE KEY uq_showtime (room_id, start_time),          -- chặn trùng giờ cơ bản; kiểm tra chồng lấn ở tầng ứng dụng
    INDEX idx_show_movie (movie_id, start_time),
    CONSTRAINT fk_show_sch   FOREIGN KEY (schedule_id) REFERENCES schedules(schedule_id),
    CONSTRAINT fk_show_movie FOREIGN KEY (movie_id)    REFERENCES movies(movie_id),
    CONSTRAINT fk_show_room  FOREIGN KEY (room_id)     REFERENCES rooms(room_id),
    CHECK (end_time > start_time)
) ENGINE=InnoDB;

CREATE TABLE showtime_seats (                              -- trạng thái ghế theo từng suất (Trống/Đang giữ/Đã bán)
    showtime_id  INT UNSIGNED NOT NULL,
    seat_id      INT UNSIGNED NOT NULL,
    status       ENUM('AVAILABLE','HELD','SOLD') NOT NULL DEFAULT 'AVAILABLE',
    held_by      INT UNSIGNED NULL,                        -- user giữ ghế
    held_until   DATETIME NULL,                            -- = giờ giữ + 5 phút
    PRIMARY KEY (showtime_id, seat_id),                    -- khóa chính ngăn bán trùng ghế
    INDEX idx_ss_hold (status, held_until),
    CONSTRAINT fk_ss_show FOREIGN KEY (showtime_id) REFERENCES showtimes(showtime_id) ON DELETE CASCADE,
    CONSTRAINT fk_ss_seat FOREIGN KEY (seat_id)     REFERENCES seats(seat_id),
    CONSTRAINT fk_ss_user FOREIGN KEY (held_by)     REFERENCES users(user_id)
) ENGINE=InnoDB;

-- =====================================================================
-- NHÓM 7. LOẠI VÉ & GIÁ VÉ (QLLV: UC32-UC34), KHUYẾN MÃI (QLSK: UC65-UC68)
-- =====================================================================
CREATE TABLE ticket_types (
    ticket_type_id  INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    type_name       VARCHAR(60) NOT NULL UNIQUE,           -- Người lớn, Trẻ em, Sinh viên...
    room_type       ENUM('2D','3D','IMAX') NULL,           -- NULL = áp dụng mọi loại phòng
    base_price      DECIMAL(10,0) NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    CHECK (base_price >= 0)
) ENGINE=InnoDB;

CREATE TABLE ticket_price_rules (                          -- giá đổi theo khung giờ / ngày trong tuần
    rule_id         INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    ticket_type_id  INT UNSIGNED NOT NULL,
    day_of_week     TINYINT UNSIGNED NULL,                 -- 1=Thứ 2 ... 7=CN; NULL = mọi ngày
    time_from       TIME NOT NULL DEFAULT '00:00:00',
    time_to         TIME NOT NULL DEFAULT '23:59:59',
    price           DECIMAL(10,0) NOT NULL,
    CONSTRAINT fk_pr_type FOREIGN KEY (ticket_type_id) REFERENCES ticket_types(ticket_type_id) ON DELETE CASCADE,
    CHECK (price >= 0)
) ENGINE=InnoDB;

CREATE TABLE promotions (                                  -- sự kiện / khuyến mãi / ngày ưu đãi (C'Day...)
    promotion_id     INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name             VARCHAR(150) NOT NULL,
    promo_type       ENUM('EVENT','DISCOUNT','SPECIAL_DAY','STUDENT') NOT NULL DEFAULT 'DISCOUNT',
    description      TEXT NULL,
    discount_percent DECIMAL(5,2) NOT NULL DEFAULT 0,      -- "Khuyến mãi" trong công thức đơn giá, vd 10.00 = 10%
    condition_text   VARCHAR(255) NULL,                    -- điều kiện áp dụng
    day_of_week      TINYINT UNSIGNED NULL,                -- ngày ưu đãi cố định trong tuần
    min_tier_id      TINYINT UNSIGNED NULL,                -- hạng thành viên tối thiểu
    start_date       DATE NOT NULL,
    end_date         DATE NOT NULL,
    is_active        BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT fk_promo_tier FOREIGN KEY (min_tier_id) REFERENCES membership_tiers(tier_id),
    CHECK (discount_percent BETWEEN 0 AND 100),
    CHECK (end_date >= start_date)                         -- "Ngày kết thúc trước ngày bắt đầu"
) ENGINE=InnoDB;

-- =====================================================================
-- NHÓM 8. F&B, KHO THEO LÔ (QLKho: UC41-UC44)
-- =====================================================================
CREATE TABLE fb_products (
    product_id   INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    product_name VARCHAR(120) NOT NULL UNIQUE,
    category     ENUM('POPCORN','DRINK','SNACK','COMBO','INGREDIENT') NOT NULL,
    unit         VARCHAR(20) NOT NULL DEFAULT 'cái',
    price        DECIMAL(10,0) NOT NULL DEFAULT 0,
    is_combo     BOOLEAN NOT NULL DEFAULT FALSE,
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    image_url    VARCHAR(255) NULL,
    CHECK (price >= 0)
) ENGINE=InnoDB;

CREATE TABLE combo_components (                            -- combo gồm những sản phẩm nào (để trừ kho)
    combo_id      INT UNSIGNED NOT NULL,
    component_id  INT UNSIGNED NOT NULL,
    quantity      SMALLINT UNSIGNED NOT NULL DEFAULT 1,
    PRIMARY KEY (combo_id, component_id),
    CONSTRAINT fk_cc_combo FOREIGN KEY (combo_id)     REFERENCES fb_products(product_id) ON DELETE CASCADE,
    CONSTRAINT fk_cc_comp  FOREIGN KEY (component_id) REFERENCES fb_products(product_id)
) ENGINE=InnoDB;

CREATE TABLE suppliers (
    supplier_id  INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name         VARCHAR(120) NOT NULL UNIQUE,
    phone        VARCHAR(15) NULL,
    address      VARCHAR(255) NULL
) ENGINE=InnoDB;

CREATE TABLE stock_receipts (                              -- phiếu nhập kho
    receipt_id    INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    supplier_id   INT UNSIGNED NOT NULL,
    received_by   INT UNSIGNED NOT NULL,                   -- employee_id
    receipt_date  DATE NOT NULL,
    note          VARCHAR(255) NULL,
    CONSTRAINT fk_rc_sup FOREIGN KEY (supplier_id) REFERENCES suppliers(supplier_id),
    CONSTRAINT fk_rc_emp FOREIGN KEY (received_by) REFERENCES employees(employee_id)
) ENGINE=InnoDB;

CREATE TABLE inventory_batches (                           -- LÔ HÀNG: mỗi lô có HSD riêng -> khắc phục "tồn kho tĩnh"
    batch_id      INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    batch_code    VARCHAR(30) NOT NULL UNIQUE,             -- hệ thống tự sinh
    receipt_id    INT UNSIGNED NOT NULL,
    product_id    INT UNSIGNED NOT NULL,
    qty_received  INT UNSIGNED NOT NULL,
    qty_remaining INT UNSIGNED NOT NULL,
    import_date   DATE NOT NULL,
    expiry_date   DATE NOT NULL,
    unit_cost     DECIMAL(10,0) NOT NULL DEFAULT 0,
    INDEX idx_batch_fifo (product_id, import_date, expiry_date),
    CONSTRAINT fk_bt_rc   FOREIGN KEY (receipt_id) REFERENCES stock_receipts(receipt_id),
    CONSTRAINT fk_bt_prod FOREIGN KEY (product_id) REFERENCES fb_products(product_id),
    CHECK (qty_remaining <= qty_received)
) ENGINE=InnoDB;

CREATE TABLE stock_alerts (                                -- UC43: quét 00:00 mỗi ngày
    alert_id     INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    batch_id     INT UNSIGNED NOT NULL,
    alert_type   ENUM('NEAR_EXPIRY','EXPIRED') NOT NULL,    -- HSD <= 7 ngày / HSD < hôm nay
    alert_date   DATE NOT NULL,
    is_handled   BOOLEAN NOT NULL DEFAULT FALSE,
    handled_by   INT UNSIGNED NULL,
    UNIQUE KEY uq_alert (batch_id, alert_type, alert_date),
    CONSTRAINT fk_al_batch FOREIGN KEY (batch_id)   REFERENCES inventory_batches(batch_id),
    CONSTRAINT fk_al_emp   FOREIGN KEY (handled_by) REFERENCES employees(employee_id)
) ENGINE=InnoDB;

-- =====================================================================
-- NHÓM 9. ĐẶT VÉ / BÁN VÉ (QLBV: UC35-UC40)
-- =====================================================================
CREATE TABLE bookings (
    booking_id      INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    booking_code    VARCHAR(20) NOT NULL UNIQUE,
    customer_id     INT UNSIGNED NOT NULL,
    showtime_id     INT UNSIGNED NOT NULL,
    sold_by         INT UNSIGNED NULL,                     -- employee_id nếu bán tại quầy; NULL nếu online
    channel         ENUM('ONLINE','COUNTER') NOT NULL DEFAULT 'ONLINE',
    promotion_id    INT UNSIGNED NULL,
    ticket_total    DECIMAL(12,0) NOT NULL DEFAULT 0,      -- Σ đơn giá vé
    combo_total     DECIMAL(12,0) NOT NULL DEFAULT 0,      -- Σ combo
    discount_amount DECIMAL(12,0) NOT NULL DEFAULT 0,      -- giảm theo hạng/ngày
    total_amount    DECIMAL(12,0) NOT NULL DEFAULT 0,      -- Tổng = vé + combo - khuyến mãi
    points_earned   INT UNSIGNED NOT NULL DEFAULT 0,       -- = total ÷ 10.000
    -- Tab "Vé của tôi": Chờ xác nhận / Sắp tới / Đang thực hiện / Đã hoàn tất / Đã hủy
    status          ENUM('PENDING_CONFIRM','UPCOMING','IN_PROGRESS','COMPLETED','CANCELLED') NOT NULL DEFAULT 'PENDING_CONFIRM',
    payment_status  ENUM('UNPAID','PAID','REFUNDED') NOT NULL DEFAULT 'UNPAID',
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    cancelled_at    DATETIME NULL,
    refund_amount   DECIMAL(12,0) NOT NULL DEFAULT 0,
    INDEX idx_bk_customer (customer_id, status),
    INDEX idx_bk_show (showtime_id),
    CONSTRAINT fk_bk_cus   FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
    CONSTRAINT fk_bk_show  FOREIGN KEY (showtime_id) REFERENCES showtimes(showtime_id),
    CONSTRAINT fk_bk_emp   FOREIGN KEY (sold_by)     REFERENCES employees(employee_id),
    CONSTRAINT fk_bk_promo FOREIGN KEY (promotion_id) REFERENCES promotions(promotion_id)
) ENGINE=InnoDB;

CREATE TABLE tickets (
    ticket_id       INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    booking_id      INT UNSIGNED NOT NULL,
    showtime_id     INT UNSIGNED NOT NULL,
    seat_id         INT UNSIGNED NOT NULL,
    ticket_type_id  INT UNSIGNED NOT NULL,
    base_price      DECIMAL(10,0) NOT NULL,
    promo_percent   DECIMAL(5,2)  NOT NULL DEFAULT 0,
    unit_price      DECIMAL(10,0) NOT NULL,                -- Đơn giá = Giá vé - (KM × Giá vé)
    qr_code         VARCHAR(64) NULL UNIQUE,               -- UC39: mã QR duy nhất
    status          ENUM('VALID','USED','CANCELLED') NOT NULL DEFAULT 'VALID',
    checked_in_at   DATETIME NULL,
    INDEX idx_tk_booking (booking_id),
    CONSTRAINT fk_tk_bk   FOREIGN KEY (booking_id)  REFERENCES bookings(booking_id) ON DELETE CASCADE,
    CONSTRAINT fk_tk_ss   FOREIGN KEY (showtime_id, seat_id) REFERENCES showtime_seats(showtime_id, seat_id),
    CONSTRAINT fk_tk_type FOREIGN KEY (ticket_type_id) REFERENCES ticket_types(ticket_type_id)
) ENGINE=InnoDB;

CREATE TABLE booking_items (                               -- combo F&B mua kèm khi đặt vé
    item_id     INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    booking_id  INT UNSIGNED NOT NULL,
    product_id  INT UNSIGNED NOT NULL,
    quantity    SMALLINT UNSIGNED NOT NULL DEFAULT 1,
    unit_price  DECIMAL(10,0) NOT NULL,
    CONSTRAINT fk_bi_bk   FOREIGN KEY (booking_id) REFERENCES bookings(booking_id) ON DELETE CASCADE,
    CONSTRAINT fk_bi_prod FOREIGN KEY (product_id) REFERENCES fb_products(product_id)
) ENGINE=InnoDB;

CREATE TABLE ticket_changes (                              -- UC40 đổi / hủy vé
    change_id      INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    ticket_id      INT UNSIGNED NOT NULL,
    change_type    ENUM('EXCHANGE','CANCEL') NOT NULL,
    new_showtime_id INT UNSIGNED NULL,
    new_seat_id     INT UNSIGNED NULL,
    refund_amount  DECIMAL(12,0) NOT NULL DEFAULT 0,
    processed_by   INT UNSIGNED NOT NULL,                  -- users.user_id (khách hoặc nhân viên)
    created_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_tc_tk   FOREIGN KEY (ticket_id)       REFERENCES tickets(ticket_id),
    CONSTRAINT fk_tc_show FOREIGN KEY (new_showtime_id) REFERENCES showtimes(showtime_id),
    CONSTRAINT fk_tc_user FOREIGN KEY (processed_by)    REFERENCES users(user_id)
) ENGINE=InnoDB;

-- =====================================================================
-- NHÓM 10. QR ORDER F&B TẠI CHỖ (QLQR: UC62-UC64)
-- =====================================================================
CREATE TABLE qr_locations (                                -- mã QR dán tại ghế / sảnh
    qr_id          INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    qr_code        VARCHAR(64) NOT NULL UNIQUE,
    location_type  ENUM('SEAT','LOBBY') NOT NULL,
    room_id        INT UNSIGNED NULL,
    seat_id        INT UNSIGNED NULL,
    label          VARCHAR(80) NULL,
    is_active      BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT fk_qr_room FOREIGN KEY (room_id) REFERENCES rooms(room_id),
    CONSTRAINT fk_qr_seat FOREIGN KEY (seat_id) REFERENCES seats(seat_id)
) ENGINE=InnoDB;

CREATE TABLE fb_orders (
    fb_order_id   INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    order_code    VARCHAR(20) NOT NULL UNIQUE,
    customer_id   INT UNSIGNED NULL,
    qr_id         INT UNSIGNED NOT NULL,
    handled_by    INT UNSIGNED NULL,                       -- employee_id phục vụ
    total_amount  DECIMAL(12,0) NOT NULL DEFAULT 0,
    payment_method ENUM('ONLINE','AT_COUNTER') NOT NULL DEFAULT 'ONLINE',
    payment_status ENUM('UNPAID','PAID') NOT NULL DEFAULT 'UNPAID',
    status        ENUM('NEW','PREPARING','DELIVERING','DONE','CANCELLED') NOT NULL DEFAULT 'NEW',
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_fo_status (status, created_at),
    CONSTRAINT fk_fo_cus FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
    CONSTRAINT fk_fo_qr  FOREIGN KEY (qr_id)       REFERENCES qr_locations(qr_id),
    CONSTRAINT fk_fo_emp FOREIGN KEY (handled_by)  REFERENCES employees(employee_id)
) ENGINE=InnoDB;

CREATE TABLE fb_order_items (
    fb_item_id   INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    fb_order_id  INT UNSIGNED NOT NULL,
    product_id   INT UNSIGNED NOT NULL,
    quantity     SMALLINT UNSIGNED NOT NULL DEFAULT 1,
    unit_price   DECIMAL(10,0) NOT NULL,
    CONSTRAINT fk_foi_order FOREIGN KEY (fb_order_id) REFERENCES fb_orders(fb_order_id) ON DELETE CASCADE,
    CONSTRAINT fk_foi_prod  FOREIGN KEY (product_id)  REFERENCES fb_products(product_id)
) ENGINE=InnoDB;

-- =====================================================================
-- NHÓM 11. THANH TOÁN, LỊCH SỬ ĐIỂM, XUẤT KHO (dùng chung)
-- =====================================================================
CREATE TABLE payments (
    payment_id    INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    booking_id    INT UNSIGNED NULL,
    fb_order_id   INT UNSIGNED NULL,
    method        ENUM('MOMO','ZALOPAY','VNPAY','CARD','CASH') NOT NULL,
    amount        DECIMAL(12,0) NOT NULL,
    status        ENUM('PENDING','SUCCESS','FAILED','REFUNDED') NOT NULL DEFAULT 'PENDING',
    transaction_ref VARCHAR(80) NULL,
    paid_at       DATETIME NULL,
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_pm_bk FOREIGN KEY (booking_id)  REFERENCES bookings(booking_id),
    CONSTRAINT fk_pm_fo FOREIGN KEY (fb_order_id) REFERENCES fb_orders(fb_order_id),
    CHECK (booking_id IS NOT NULL OR fb_order_id IS NOT NULL)
) ENGINE=InnoDB;

CREATE TABLE point_history (                               -- UC45, UC47
    point_id     INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    customer_id  INT UNSIGNED NOT NULL,
    booking_id   INT UNSIGNED NULL,
    points       INT NOT NULL,                             -- dương = cộng, âm = trừ (hủy vé)
    reason       VARCHAR(120) NULL,
    created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_ph_cus FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
    CONSTRAINT fk_ph_bk  FOREIGN KEY (booking_id)  REFERENCES bookings(booking_id)
) ENGINE=InnoDB;

CREATE TABLE stock_movements (                             -- UC44: ghi nhận xuất kho FIFO
    movement_id   INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    batch_id      INT UNSIGNED NOT NULL,
    movement_type ENUM('IN','OUT_SALE','OUT_EXPIRED','ADJUST') NOT NULL,
    quantity      INT NOT NULL,
    booking_id    INT UNSIGNED NULL,
    fb_order_id   INT UNSIGNED NULL,
    created_by    INT UNSIGNED NULL,
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_sm_batch (batch_id),
    CONSTRAINT fk_sm_batch FOREIGN KEY (batch_id)    REFERENCES inventory_batches(batch_id),
    CONSTRAINT fk_sm_bk    FOREIGN KEY (booking_id)  REFERENCES bookings(booking_id),
    CONSTRAINT fk_sm_fo    FOREIGN KEY (fb_order_id) REFERENCES fb_orders(fb_order_id),
    CONSTRAINT fk_sm_emp   FOREIGN KEY (created_by)  REFERENCES employees(employee_id)
) ENGINE=InnoDB;

SET FOREIGN_KEY_CHECKS = 1;

-- =====================================================================
-- VIEW PHỤC VỤ BÁO CÁO (BCTK: UC56-UC61)
-- =====================================================================
CREATE OR REPLACE VIEW v_ticket_revenue AS               -- UC56 doanh thu vé theo phim/rạp/ngày
SELECT m.movie_id, m.title, c.cinema_id, c.name AS cinema_name,
       DATE(s.start_time) AS show_date,
       COUNT(t.ticket_id) AS tickets_sold,
       SUM(t.unit_price)  AS revenue
FROM tickets t
JOIN bookings b  ON b.booking_id = t.booking_id AND b.payment_status = 'PAID'
JOIN showtimes s ON s.showtime_id = t.showtime_id
JOIN movies m    ON m.movie_id = s.movie_id
JOIN rooms r     ON r.room_id = s.room_id
JOIN cinemas c   ON c.cinema_id = r.cinema_id
WHERE t.status <> 'CANCELLED'
GROUP BY m.movie_id, m.title, c.cinema_id, c.name, DATE(s.start_time);

CREATE OR REPLACE VIEW v_occupancy AS                     -- UC58: (vé bán / tổng ghế) x 100%
SELECT s.showtime_id, m.title, r.room_name, s.start_time,
       r.capacity AS total_seats,
       SUM(ss.status = 'SOLD') AS sold_seats,
       ROUND(SUM(ss.status = 'SOLD') / COUNT(*) * 100, 2) AS occupancy_percent
FROM showtimes s
JOIN movies m ON m.movie_id = s.movie_id
JOIN rooms r  ON r.room_id = s.room_id
JOIN showtime_seats ss ON ss.showtime_id = s.showtime_id
GROUP BY s.showtime_id, m.title, r.room_name, s.start_time, r.capacity;

CREATE OR REPLACE VIEW v_stock_by_batch AS                -- UC42, UC59 tồn kho theo lô
SELECT b.batch_id, b.batch_code, p.product_name, b.qty_remaining, b.import_date, b.expiry_date,
       DATEDIFF(b.expiry_date, CURDATE()) AS days_left,
       CASE WHEN b.expiry_date < CURDATE() THEN 'EXPIRED'
            WHEN DATEDIFF(b.expiry_date, CURDATE()) <= 7 THEN 'NEAR_EXPIRY'
            ELSE 'OK' END AS expiry_state
FROM inventory_batches b
JOIN fb_products p ON p.product_id = b.product_id;

CREATE OR REPLACE VIEW v_distributor_share AS             -- UC61
SELECT m.movie_id, m.title, d.name AS distributor, dc.share_percent,
       SUM(v.revenue) AS ticket_revenue,
       ROUND(SUM(v.revenue) * dc.share_percent / 100, 0) AS distributor_amount
FROM v_ticket_revenue v
JOIN movies m ON m.movie_id = v.movie_id
JOIN distributor_contracts dc ON dc.movie_id = m.movie_id
JOIN distributors d ON d.distributor_id = dc.distributor_id
GROUP BY m.movie_id, m.title, d.name, dc.share_percent;
