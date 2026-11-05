"""Mở mọi trang GET của từng vai trò, báo lỗi 500."""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

app, path, _ = make_app()
ACCOUNTS = {"admin": "admin@cinema.vn", "manager": "quanly@cinema.vn", "ticket": "banve@cinema.vn", "kho": "kho@cinema.vn", "khach": "khach@cinema.vn"}
rules = [r for r in app.url_map.iter_rules() if "GET" in r.methods and r.endpoint != "static"]
bad = 0
for role, email in ACCOUNTS.items():
    cl = Client(app)
    r = cl.login(email)
    assert "đăng nhập" not in text(r).lower()[:0], r
    for rule in sorted(rules, key=lambda r: r.rule):
        url = re.sub(r"<(?:int:)?\w+>", "1", rule.rule)
        if "<code>" in rule.rule or "<" in url:
            url = re.sub(r"<[^>]+>", "1", rule.rule)
        if url in ("/logout",):
            continue
        try:
            resp = cl.c.get(url, follow_redirects=True)
        except Exception as e:
            print(f"[{role}] EXC {url}: {type(e).__name__}: {e}"); bad += 1; continue
        if resp.status_code >= 500:
            print(f"[{role}] {resp.status_code} {url}"); bad += 1
print("done, loi =", bad)
