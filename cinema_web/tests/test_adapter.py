"""Kiểm thử mẫu Adapter (cinema/mail.py):  python tests/test_adapter.py
Không cần CSDL: chỉ kiểm tra việc chọn adapter và cách adapter gọi smtplib (dùng SMTP giả)."""
import contextlib
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import smtplib  # noqa: E402
from cinema import create_app, services as sv  # noqa: E402
from cinema import mail  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(("  ok   " if cond else "  LOI  ") + name)


class FakeSMTP:
    calls = []
    boom = False

    def __init__(self, host, port, timeout=None):
        if FakeSMTP.boom:
            raise OSError("không kết nối được")
        FakeSMTP.calls.append(("connect", host, port))

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        FakeSMTP.calls.append(("starttls",))

    def login(self, u, p):
        FakeSMTP.calls.append(("login", u, p))

    def send_message(self, msg):
        FakeSMTP.calls.append(("send", msg["From"], msg["To"], msg["Subject"], msg.get_content().strip()))


app = create_app({"TESTING": True, "ENABLE_SCHEDULER": False})
real_smtp = smtplib.SMTP
smtplib.SMTP = FakeSMTP
try:
    with app.app_context():
        # 1. chưa cấu hình SMTP -> adapter Console
        app.config["MAIL_HOST"] = ""
        s = mail.get_email_sender()
        check("không có MAIL_HOST -> ConsoleEmailSender", isinstance(s, mail.ConsoleEmailSender))
        check("ConsoleEmailSender là một EmailSender", isinstance(s, mail.EmailSender))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            sv.send_mail("a@b.vn", "Tiêu đề", "Nội dung")
        out = buf.getvalue()
        check("send_mail in [MAIL-DEV] ra console", "[MAIL-DEV] To: a@b.vn | Tiêu đề" in out and "Nội dung" in out)

        # 2. có SMTP -> adapter SMTP, có đăng nhập
        app.config.update(MAIL_HOST="smtp.test", MAIL_PORT=587, MAIL_USER="u", MAIL_PASSWORD="p", MAIL_FROM="rap@cinema.vn")
        s = mail.get_email_sender()
        check("có MAIL_HOST -> SmtpEmailSender", isinstance(s, mail.SmtpEmailSender))
        check("SmtpEmailSender là một EmailSender", isinstance(s, mail.EmailSender))
        FakeSMTP.calls.clear()
        sv.send_mail("khach@x.vn", "Vé xem phim BK1", "Xin chào")
        check("kết nối đúng host/port", ("connect", "smtp.test", 587) in FakeSMTP.calls)
        check("có starttls rồi login", ("starttls",) in FakeSMTP.calls and ("login", "u", "p") in FakeSMTP.calls)
        check("thư gửi đúng người nhận / tiêu đề / nội dung",
              ("send", "rap@cinema.vn", "khach@x.vn", "Vé xem phim BK1", "Xin chào") in FakeSMTP.calls)

        # 3. SMTP không cần tài khoản -> bỏ qua login
        app.config["MAIL_USER"] = ""
        FakeSMTP.calls.clear()
        sv.send_mail("khach@x.vn", "T", "N")
        check("MAIL_USER rỗng -> không gọi login", not any(c[0] == "login" for c in FakeSMTP.calls))

        # 4. lỗi SMTP không làm hỏng giao dịch
        FakeSMTP.boom = True
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                sv.send_mail("khach@x.vn", "T", "N")
            check("lỗi SMTP bị nuốt, không ném exception", True)
        except Exception:
            check("lỗi SMTP bị nuốt, không ném exception", False)
        check("lỗi SMTP được ghi [MAIL-ERROR]", "[MAIL-ERROR]" in buf.getvalue())
        FakeSMTP.boom = False
finally:
    smtplib.SMTP = real_smtp

print(f"\n==== ADAPTER: {len(PASS)} đạt, {len(FAIL)} lỗi ====")
sys.exit(1 if FAIL else 0)
