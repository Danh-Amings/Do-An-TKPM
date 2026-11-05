"""Lớp truy cập MySQL rất mỏng. Mỗi request = 1 transaction (commit khi thành công, rollback khi lỗi)."""
from flask import g, current_app


def connect():
    import pymysql
    import pymysql.cursors
    c = current_app.config
    return pymysql.connect(
        host=c["DB_HOST"], port=c["DB_PORT"], user=c["DB_USER"], password=c["DB_PASSWORD"],
        database=c["DB_NAME"], charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor, autocommit=False,
    )


def get_db():
    if "db" not in g:
        g.db = connect()
    return g.db


def q(sql, args=()):
    """SELECT nhiều dòng -> list[dict]"""
    cur = get_db().cursor()
    cur.execute(sql, args)
    rows = list(cur.fetchall())
    cur.close()
    return rows


def q1(sql, args=()):
    rows = q(sql, args)
    return rows[0] if rows else None


def ex(sql, args=()):
    """INSERT/UPDATE/DELETE -> lastrowid"""
    cur = get_db().cursor()
    cur.execute(sql, args)
    last = cur.lastrowid
    cur.close()
    return last


def run(sql, args=()):
    """INSERT/UPDATE/DELETE -> số dòng bị ảnh hưởng"""
    cur = get_db().cursor()
    cur.execute(sql, args)
    n = cur.rowcount
    cur.close()
    return n


def in_clause(values):
    """Tạo chuỗi %s,%s,%s cho mệnh đề IN"""
    return ",".join(["%s"] * len(values))


def commit():
    if "db" in g:
        g.db.commit()


def rollback():
    if "db" in g:
        g.db.rollback()


def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        try:
            if exc is not None:
                db.rollback()
        finally:
            db.close()
