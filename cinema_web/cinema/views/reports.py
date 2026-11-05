"""BCTK: UC56-UC61 (báo cáo - thống kê). Xuất: CSV (mở bằng Excel) và trang in/PDF của trình duyệt."""
import csv
import io
from datetime import date, datetime, timedelta

from flask import Blueprint, render_template, request, Response, g

from ..db import q, q1
from ..security import roles_required, MANAGER
from .. import services as sv

bp = Blueprint("reports", __name__)


def rng():
    a = request.args
    today = date.today()
    lo = sv.to_date(a["from"]) if a.get("from") else today.replace(day=1)
    hi = sv.to_date(a["to"]) if a.get("to") else today
    return lo, hi, datetime(lo.year, lo.month, lo.day), datetime(hi.year, hi.month, hi.day) + timedelta(days=1)


def csv_response(name, header, rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    return Response("﻿" + buf.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename={name}.csv"})


@bp.route("/reports")
@roles_required(MANAGER)
def index():
    return render_template("reports/index.html")


# ------------------------------------------------------------------ UC56 Doanh thu vé
def ticket_rows(lo_dt, hi_dt):
    return q("SELECT DATE(s.start_time) AS d, m.movie_id, m.title, c.name AS cinema, COUNT(t.ticket_id) AS n, SUM(t.unit_price) AS rev "
             "FROM tickets t JOIN bookings b ON b.booking_id=t.booking_id JOIN showtimes s ON s.showtime_id=t.showtime_id "
             "JOIN movies m ON m.movie_id=s.movie_id JOIN rooms r ON r.room_id=s.room_id JOIN cinemas c ON c.cinema_id=r.cinema_id "
             "WHERE b.payment_status IN ('PAID') AND t.status<>'CANCELLED' AND s.start_time>=%s AND s.start_time<%s "
             "GROUP BY DATE(s.start_time), m.movie_id, m.title, c.name", (lo_dt, hi_dt))


@bp.route("/reports/ticket-revenue")
@roles_required(MANAGER)
def ticket_revenue():
    lo, hi, lo_dt, hi_dt = rng()
    by = request.args.get("by", "movie")
    raw = ticket_rows(lo_dt, hi_dt)
    agg = {}
    for r in raw:
        d = str(r["d"])[:10]
        key = {"movie": r["title"], "cinema": r["cinema"], "day": d, "month": d[:7]}.get(by, r["title"])
        a = agg.setdefault(key, [0, 0])
        a[0] += int(r["n"])
        a[1] += int(r["rev"] or 0)
    rows = sorted(agg.items(), key=lambda kv: kv[0] if by in ("day", "month") else -kv[1][1])
    label = {"movie": "Phim", "cinema": "Rạp", "day": "Ngày", "month": "Tháng"}[by]
    if request.args.get("export") == "csv":
        return csv_response("doanh-thu-ve", [label, "Số vé", "Doanh thu"], [(k, v[0], v[1]) for k, v in rows])
    return render_template("reports/ticket_revenue.html", rows=rows, by=by, label=label, lo=lo, hi=hi,
                           total=sum(v[1] for _, v in rows), count=sum(v[0] for _, v in rows))


# ------------------------------------------------------------------ UC57 Doanh thu F&B
@bp.route("/reports/fnb-revenue")
@roles_required(MANAGER)
def fnb_revenue():
    lo, hi, lo_dt, hi_dt = rng()
    b = q("SELECT DATE(b.created_at) AS d, p.product_name, SUM(i.quantity) AS qty, SUM(i.quantity*i.unit_price) AS rev "
          "FROM booking_items i JOIN bookings b ON b.booking_id=i.booking_id JOIN fb_products p ON p.product_id=i.product_id "
          "WHERE b.payment_status='PAID' AND b.status<>'CANCELLED' AND b.created_at>=%s AND b.created_at<%s "
          "GROUP BY DATE(b.created_at), p.product_name", (lo_dt, hi_dt))
    o = q("SELECT DATE(f.created_at) AS d, p.product_name, SUM(i.quantity) AS qty, SUM(i.quantity*i.unit_price) AS rev "
          "FROM fb_order_items i JOIN fb_orders f ON f.fb_order_id=i.fb_order_id JOIN fb_products p ON p.product_id=i.product_id "
          "WHERE f.payment_status='PAID' AND f.status<>'CANCELLED' AND f.created_at>=%s AND f.created_at<%s "
          "GROUP BY DATE(f.created_at), p.product_name", (lo_dt, hi_dt))
    by_day, by_prod = {}, {}
    for src, rows in (("Kèm vé", b), ("QR Order", o)):
        for r in rows:
            d = str(r["d"])[:10]
            by_day.setdefault(d, {"Kèm vé": 0, "QR Order": 0})[src] += int(r["rev"] or 0)
            a = by_prod.setdefault(r["product_name"], [0, 0])
            a[0] += int(r["qty"])
            a[1] += int(r["rev"] or 0)
    days = sorted(by_day.items())
    prods = sorted(by_prod.items(), key=lambda kv: -kv[1][1])
    if request.args.get("export") == "csv":
        return csv_response("doanh-thu-fnb", ["Sản phẩm", "Số lượng", "Doanh thu"], [(k, v[0], v[1]) for k, v in prods])
    return render_template("reports/fnb_revenue.html", days=days, prods=prods, lo=lo, hi=hi, total=sum(v[1] for _, v in prods))


# ------------------------------------------------------------------ UC58 Tỷ lệ lấp đầy
@bp.route("/reports/occupancy")
@roles_required(MANAGER)
def occupancy():
    lo, hi, lo_dt, hi_dt = rng()
    movie = request.args.get("movie", type=int)
    sql = ("SELECT s.showtime_id, s.start_time, m.title, r.room_name, SUM(CASE WHEN ss.status='SOLD' THEN 1 ELSE 0 END) AS sold, "
           "COUNT(ss.seat_id) AS total FROM showtimes s JOIN movies m ON m.movie_id=s.movie_id JOIN rooms r ON r.room_id=s.room_id "
           "JOIN showtime_seats ss ON ss.showtime_id=s.showtime_id WHERE s.status<>'CANCELLED' AND s.start_time>=%s AND s.start_time<%s")
    args = [lo_dt, hi_dt]
    if movie:
        sql += " AND s.movie_id=%s"
        args.append(movie)
    rows = q(sql + " GROUP BY s.showtime_id, s.start_time, m.title, r.room_name ORDER BY s.start_time", tuple(args))
    for r in rows:
        r["pct"] = round(int(r["sold"]) / int(r["total"]) * 100, 1) if int(r["total"]) else 0      # (Số vé bán / Tổng ghế) x 100%
    if request.args.get("export") == "csv":
        return csv_response("ty-le-lap-day", ["Suất chiếu", "Phim", "Phòng", "Vé bán", "Tổng ghế", "Tỷ lệ %"],
                            [(sv.to_dt(r["start_time"]).strftime("%d/%m/%Y %H:%M"), r["title"], r["room_name"], r["sold"], r["total"], r["pct"]) for r in rows])
    avg = round(sum(r["pct"] for r in rows) / len(rows), 1) if rows else 0
    return render_template("reports/occupancy.html", rows=rows, lo=lo, hi=hi, avg=avg, movie=movie,
                           movies=q("SELECT movie_id, title FROM movies ORDER BY title"))


# ------------------------------------------------------------------ UC59 Tồn kho & cảnh báo HSD
@bp.route("/reports/stock")
@roles_required(MANAGER)
def stock_report():
    from .fnb import expiry_state
    rows = q("SELECT b.*, p.product_name, p.unit FROM inventory_batches b JOIN fb_products p ON p.product_id=b.product_id "
             "ORDER BY p.product_name, b.expiry_date")
    today = date.today()
    for r in rows:
        r["state"] = expiry_state(r["expiry_date"], today) if r["qty_remaining"] > 0 else "EMPTY"
    summary = q("SELECT p.product_name, SUM(b.qty_remaining) AS qty FROM inventory_batches b JOIN fb_products p ON p.product_id=b.product_id "
                "WHERE b.expiry_date>=%s GROUP BY p.product_name ORDER BY p.product_name", (today,))
    if request.args.get("export") == "csv":
        return csv_response("ton-kho", ["Mã lô", "Sản phẩm", "Còn lại", "Ngày nhập", "HSD", "Trạng thái"],
                            [(r["batch_code"], r["product_name"], r["qty_remaining"], sv.to_date(r["import_date"]), sv.to_date(r["expiry_date"]), r["state"]) for r in rows])
    return render_template("reports/stock.html", rows=rows, summary=summary)


# ------------------------------------------------------------------ UC60 Chấm công & vi phạm
@bp.route("/reports/attendance")
@roles_required(MANAGER)
def attendance_report():
    lo, hi, lo_dt, hi_dt = rng()
    rows = q("SELECT u.full_name, e.employment_type, r.work_date, s.shift_name, a.check_in, a.check_out, a.late_minutes, a.is_violation, "
             "a.status FROM attendance a JOIN shift_registrations r ON r.registration_id=a.registration_id JOIN shifts s ON s.shift_id=r.shift_id "
             "JOIN employees e ON e.employee_id=r.employee_id JOIN users u ON u.user_id=e.user_id WHERE r.work_date>=%s AND r.work_date<=%s "
             "ORDER BY r.work_date DESC, u.full_name", (lo, hi))
    per = {}
    for r in rows:
        p = per.setdefault(r["full_name"], dict(shifts=0, hours=0.0, viol=0, incomplete=0))
        p["shifts"] += 1
        p["viol"] += 1 if r["is_violation"] else 0
        p["incomplete"] += 1 if r["status"] == "INCOMPLETE" else 0
        if r["check_in"] and r["check_out"]:
            p["hours"] += (sv.to_dt(r["check_out"]) - sv.to_dt(r["check_in"])).total_seconds() / 3600
    if request.args.get("export") == "csv":
        return csv_response("cham-cong", ["Nhân viên", "Ngày", "Ca", "Vào", "Ra", "Muộn (phút)", "Vi phạm", "Trạng thái"],
                            [(r["full_name"], sv.to_date(r["work_date"]), r["shift_name"], r["check_in"], r["check_out"], r["late_minutes"],
                              "Có" if r["is_violation"] else "", r["status"]) for r in rows])
    return render_template("reports/attendance.html", rows=rows, per=per, lo=lo, hi=hi)


# ------------------------------------------------------------------ UC61 Chia sẻ doanh thu với nhà phát hành
@bp.route("/reports/revenue-share")
@roles_required(MANAGER)
def revenue_share():
    lo, hi, lo_dt, hi_dt = rng()
    dist = request.args.get("distributor", type=int)
    movie = request.args.get("movie", type=int)
    rev = {}
    for r in ticket_rows(lo_dt, hi_dt):
        rev[r["movie_id"]] = rev.get(r["movie_id"], 0) + int(r["rev"] or 0)
    sql = ("SELECT dc.*, m.title, d.name AS distributor FROM distributor_contracts dc JOIN movies m ON m.movie_id=dc.movie_id "
           "JOIN distributors d ON d.distributor_id=dc.distributor_id WHERE 1=1")
    args = []
    if dist:
        sql += " AND dc.distributor_id=%s"
        args.append(dist)
    if movie:
        sql += " AND dc.movie_id=%s"
        args.append(movie)
    rows = []
    for c in q(sql + " ORDER BY d.name, m.title", tuple(args)):
        t = rev.get(c["movie_id"], 0)
        rows.append(dict(c, revenue=t, share=int(round(t * float(c["share_percent"]) / 100)), keep=t - int(round(t * float(c["share_percent"]) / 100))))
    if request.args.get("export") == "csv":
        return csv_response("chia-se-doanh-thu", ["Nhà phát hành", "Phim", "Doanh thu vé", "Tỷ lệ %", "Trả nhà phát hành", "Rạp giữ lại"],
                            [(r["distributor"], r["title"], r["revenue"], r["share_percent"], r["share"], r["keep"]) for r in rows])
    return render_template("reports/revenue_share.html", rows=rows, lo=lo, hi=hi, dist=dist, movie=movie,
                           distributors=q("SELECT * FROM distributors ORDER BY name"), movies=q("SELECT movie_id, title FROM movies ORDER BY title"),
                           total=sum(r["revenue"] for r in rows), total_share=sum(r["share"] for r in rows))
