"""MẪU ADAPTER - gửi email.

Target  : EmailSender        - giao diện mà ứng dụng mong đợi:  send(to, subject, body)
Adaptee : smtplib.SMTP       - thư viện chuẩn có giao diện khác (connect, starttls, login, send_message...)
Adapter : SmtpEmailSender    - bọc smtplib để khớp với EmailSender
          ConsoleEmailSender - cài đặt thay thế dùng khi phát triển (in ra console)

Nhờ vậy nghiệp vụ (đăng ký OTP, vé điện tử...) chỉ phụ thuộc EmailSender,
muốn đổi sang SendGrid/Mailgun chỉ cần viết thêm một adapter mới.
"""
import smtplib
from abc import ABC, abstractmethod
from email.message import EmailMessage

from flask import current_app


class EmailSender(ABC):
    """Target: giao diện chung cho mọi cách gửi email."""

    @abstractmethod
    def send(self, to, subject, body):
        ...


class ConsoleEmailSender(EmailSender):
    """Chế độ phát triển: chưa cấu hình SMTP thì in nội dung email ra console."""

    def send(self, to, subject, body):
        print(f"[MAIL-DEV] To: {to} | {subject}\n{body}\n")


class SmtpEmailSender(EmailSender):
    """Adapter: chuyển lời gọi send(to, subject, body) thành các bước của smtplib."""

    def __init__(self, host, port, user, password, sender):
        self.host, self.port = host, port
        self.user, self.password = user, password
        self.sender = sender

    def send(self, to, subject, body):
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.sender, to, subject
        msg.set_content(body)
        try:
            with smtplib.SMTP(self.host, self.port, timeout=10) as s:
                s.starttls()
                if self.user:
                    s.login(self.user, self.password)
                s.send_message(msg)
        except Exception as e:  # không để lỗi mail làm hỏng giao dịch
            print("[MAIL-ERROR]", e)


def get_email_sender():
    """Chọn adapter theo cấu hình: có MAIL_HOST -> SMTP, không có -> Console."""
    cfg = current_app.config
    if not cfg["MAIL_HOST"]:
        return ConsoleEmailSender()
    return SmtpEmailSender(cfg["MAIL_HOST"], cfg["MAIL_PORT"], cfg["MAIL_USER"],
                           cfg["MAIL_PASSWORD"], cfg["MAIL_FROM"])
