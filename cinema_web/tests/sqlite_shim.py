"""Giả lập MySQL bằng SQLite để kiểm thử logic ứng dụng khi không có MySQL.
Chỉ dùng cho tests/ - ứng dụng thật luôn chạy PyMySQL + MySQL."""
import os
import re
import sqlite3
from datetime import datetime, date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _adapt_dt(v):
    return v.strftime("%Y-%m-%d %H:%M:%S")


sqlite3.register_adapter(datetime, _adapt_dt)
sqlite3.register_adapter(date, lambda v: v.isoformat())
sqlite3.register_converter("DATETIME", lambda b: datetime.fromisoformat(b.decode().replace(" ", "T")))
sqlite3.register_converter("DATE", lambda b: date.fromisoformat(b.decode()[:10]))


def convert_ddl(text):
    text = re.sub(r"--[^\n]*", "", text)
    text = re.sub(r"ENGINE\s*=\s*\w+[^;]*", "", text)
    text = re.sub(r"\b(?:TINYINT|SMALLINT|MEDIUMINT|BIGINT|INT)(?:\s+UNSIGNED)?\s+AUTO_INCREMENT\s+PRIMARY\s+KEY",
                  "INTEGER PRIMARY KEY AUTOINCREMENT", text, flags=re.I)
    text = re.sub(r"\bUNSIGNED\b", "", text, flags=re.I)
    text = re.sub(r"\bENUM\s*\([^)]*\)", "TEXT", text, flags=re.I)
    text = re.sub(r"ON\s+UPDATE\s+CURRENT_TIMESTAMP", "", text, flags=re.I)
    text = re.sub(r"COMMENT\s+'[^']*'", "", text, flags=re.I)
    text = re.sub(r"UNIQUE\s+KEY\s+\w+\s*\(", "UNIQUE (", text, flags=re.I)
    text = re.sub(r"^\s*(?:INDEX|KEY)\s+\w+\s*\([^)]*\)\s*,?\s*$", "", text, flags=re.I | re.M)
    text = re.sub(r"^\s*FULLTEXT\s+(?:KEY|INDEX)\s+\w+\s*\([^)]*\)\s*,?\s*$", "", text, flags=re.I | re.M)
    text = re.sub(r"CREATE\s+OR\s+REPLACE\s+VIEW", "CREATE VIEW", text, flags=re.I)
    text = re.sub(r",\s*\n\s*\)", "\n)", text)
    return text


def statements(text):
    buf = ""
    for line in text.splitlines(True):
        buf += line
        if sqlite3.complete_statement(buf):
            yield buf.strip()
            buf = ""
    if buf.strip():
        yield buf.strip()


def install(path):
    con = sqlite3.connect(path)
    con.execute("PRAGMA foreign_keys=OFF")
    con.create_function("CURDATE", 0, lambda: date.today().isoformat())
    con.create_function("DATEDIFF", 2, lambda a, b: (date.fromisoformat(str(a)[:10]) - date.fromisoformat(str(b)[:10])).days)
    skipped = []
    schema = convert_ddl(open(os.path.join(ROOT, "db", "schema.sql"), encoding="utf-8").read())
    for st in statements(schema):
        if re.match(r"(DROP|CREATE)\s+DATABASE|USE\s|SET\s", st, re.I):
            continue
        try:
            con.execute(st)
        except sqlite3.Error as e:
            skipped.append((st[:60].replace("\n", " "), str(e)))
    seed = open(os.path.join(ROOT, "db", "seed.sql"), encoding="utf-8").read()
    seed = re.sub(r"--[^\n]*", "", seed)
    def _ts(m):
        return "'%s %s'" % ((date.today() + timedelta(days=int(m.group(1)))).isoformat(), m.group(2))
    seed = re.sub(r"TIMESTAMP\(DATE_ADD\(CURDATE\(\), INTERVAL (\d+) DAY\),\s*'([\d:]+)'\)", _ts, seed)
    seed = re.sub(r"DATE_ADD\(CURDATE\(\), INTERVAL (-?\d+) DAY\)",
                  lambda m: "'%s'" % (date.today() + timedelta(days=int(m.group(1)))).isoformat(), seed)
    seed = seed.replace("CURDATE()", "'%s'" % date.today().isoformat())
    pw = re.search(r"SET\s+@pw\s*=\s*('[^']*')", seed).group(1)
    seed = seed.replace("@pw", pw)
    for st in statements(seed):
        if re.match(r"USE\s|SET\s", st, re.I):
            continue
        try:
            con.execute(st)
        except sqlite3.Error as e:
            skipped.append((st[:80].replace("\n", " "), str(e)))
    con.commit()
    con.close()
    return skipped


class Cursor:
    def __init__(self, con):
        self.cur = con.cursor()
        self.lastrowid = None
        self.rowcount = 0

    @staticmethod
    def fix(sql):
        sql = sql.replace("%s", "?")
        sql = re.sub(r"\s+FOR\s+UPDATE\b", "", sql, flags=re.I)
        return sql

    def execute(self, sql, args=()):
        self.cur.execute(self.fix(sql), tuple(args))
        self.lastrowid = self.cur.lastrowid
        self.rowcount = self.cur.rowcount

    def fetchall(self):
        cols = [d[0] for d in self.cur.description or []]
        return [dict(zip(cols, r)) for r in self.cur.fetchall()]

    def close(self):
        self.cur.close()


class Conn:
    def __init__(self, path):
        self.con = sqlite3.connect(path, detect_types=sqlite3.PARSE_DECLTYPES, timeout=30)
        self.con.execute("PRAGMA foreign_keys=ON")
        self.con.create_function("CURDATE", 0, lambda: date.today().isoformat())
        self.con.create_function("DATEDIFF", 2, lambda a, b: (date.fromisoformat(str(a)[:10]) - date.fromisoformat(str(b)[:10])).days)

    def cursor(self):
        return Cursor(self.con)

    def commit(self):
        self.con.commit()

    def rollback(self):
        self.con.rollback()

    def close(self):
        self.con.close()
