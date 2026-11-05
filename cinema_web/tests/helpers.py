import re
from run_app import make_app


class Client:
    def __init__(self, app):
        self.app = app
        self.c = app.test_client()

    def csrf(self):
        with self.c.session_transaction() as s:
            if "_csrf" not in s:
                s["_csrf"] = "testtoken"
            return s["_csrf"]

    def get(self, url, **kw):
        return self.c.get(url, follow_redirects=kw.pop("follow", True), **kw)

    def post(self, url, data=None, follow=True, **kw):
        d = dict(data or {})
        d["_csrf"] = self.csrf()
        return self.c.post(url, data=d, follow_redirects=follow, **kw)

    def post_json(self, url, obj):
        return self.c.post(url, json=obj, headers={"X-CSRF-Token": self.csrf()})

    def login(self, email, pw="Admin@123"):
        self.c.get("/logout")
        r = self.post("/login", dict(email=email, password=pw))
        return r


def text(r):
    return r.get_data(as_text=True)
