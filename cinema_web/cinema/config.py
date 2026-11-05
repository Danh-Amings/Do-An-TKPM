import os


def _load_env():
    """Đọc file .env (nếu có) để khỏi cần cài thêm thư viện."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


_load_env()


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-doi-khi-nop-bai")
    DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
    DB_PORT = int(os.getenv("DB_PORT", "3306"))
    DB_USER = os.getenv("DB_USER", "root")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "")
    DB_NAME = os.getenv("DB_NAME", "cinema_booking")

    # Báo cáo: "mọi người dùng phải đăng nhập trước khi sử dụng"
    REQUIRE_LOGIN = True

    # Gửi OTP: nếu không cấu hình SMTP thì in ra console và (khi DEV_SHOW_OTP=1) hiện trên màn hình
    DEV_SHOW_OTP = os.getenv("DEV_SHOW_OTP", "1") == "1"
    MAIL_HOST = os.getenv("MAIL_HOST", "")
    MAIL_PORT = int(os.getenv("MAIL_PORT", "587"))
    MAIL_USER = os.getenv("MAIL_USER", "")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")
    MAIL_FROM = os.getenv("MAIL_FROM", "no-reply@cinema.vn")

    # Job chạy 00:00 hằng ngày (UC43)
    ENABLE_SCHEDULER = os.getenv("ENABLE_SCHEDULER", "1") == "1"

    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "uploads")
    MAX_CONTENT_LENGTH = 12 * 1024 * 1024
    AVATAR_MAX_BYTES = 5 * 1024 * 1024  # UC05: 5MB
