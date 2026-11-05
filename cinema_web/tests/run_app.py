"""Tạo ứng dụng Flask chạy trên SQLite giả lập (dùng cho test)."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sqlite_shim  # noqa: E402


def make_app(keep=False):
    path = os.path.join(tempfile.mkdtemp(), "t.db")
    skipped = sqlite_shim.install(path)
    os.environ["ENABLE_SCHEDULER"] = "0"
    import cinema.db as dbm
    dbm.connect = lambda: sqlite_shim.Conn(path)
    from cinema import create_app
    app = create_app()
    app.config.update(TESTING=False, PROPAGATE_EXCEPTIONS=False)
    return app, path, skipped


if __name__ == "__main__":
    app, path, skipped = make_app()
    print(path)
    for s in skipped:
        print("SKIP", s)
