"""QLPC: UC16-19 (phòng chiếu) · QLGN: UC20-22 (ghế) · QLSC: UC23-26 (suất chiếu) · QLLC: UC27-31 (lịch chiếu)"""
import secrets
from datetime import datetime, timedelta, date

from flask import Blueprint, render_template, request, redirect, url_for, flash, g

from ..db import q, q1, ex, run, in_clause
from ..security import roles_required, MANAGER, TICKET_STAFF, login_required
from .. import services as sv

bp = Blueprint("cinema", __name__)
ROOM_TYPES = ["2D", "3D", "IMAX"]
SEATS_PER_ROW = 10


#  QLPC - Phòng chiếu
def _build_seats(room_id, room_name, frm, to):
    """Tạo ghế từ số thứ tự frm..to-1 (mỗi hàng 10 ghế), mặc định loại Standard, kèm mã QR gọi món tại ghế."""
    std = q1("SELECT seat_type_id FROM seat_types WHERE type_name='Standard'") or q1("SELECT seat_type_id FROM seat_types ORDER BY seat_type_id")
    for i in range(frm, to):
        row, num = chr(65 + i // SEATS_PER_ROW), i % SEATS_PER_ROW + 1
        sid = ex("INSERT INTO seats (room_id, seat_type_id, row_label, seat_number) VALUES (%s,%s,%s,%s)",
                 (room_id, std["seat_type_id"], row, num))
        ex("INSERT INTO qr_locations (qr_code, location_type, room_id, seat_id, label) VALUES (%s,'SEAT',%s,%s,%s)",
           (secrets.token_urlsafe(10), room_id, sid, f"{room_name} - Ghế {row}{num}"))


def sync_showtime_seats(showtime_id):
    run("INSERT INTO showtime_seats (showtime_id, seat_id) SELECT %s, s.seat_id FROM showtimes st JOIN seats s ON s.room_id=st.room_id "
        "WHERE st.showtime_id=%s AND s.is_active=1 AND NOT EXISTS (SELECT 1 FROM showtime_seats x WHERE x.showtime_id=st.showtime_id "
        "AND x.seat_id=s.seat_id)", (showtime_id, showtime_id))


@bp.route("/manage/rooms")
@roles_required(MANAGER)
def room_list():                                                                      # UC16
    rows = q("SELECT r.*, c.name AS cinema, (SELECT COUNT(*) FROM showtimes s WHERE s.room_id=r.room_id AND s.status='SCHEDULED' "
             "AND s.end_time>=%s) AS active_shows FROM rooms r JOIN cinemas c ON c.cinema_id=r.cinema_id ORDER BY c.name, r.room_name",
             (sv.now(),))
    return render_template("cinema/rooms.html", rows=rows)


@bp.route("/manage/rooms/add", methods=["GET", "POST"])
@roles_required(MANAGER)
def room_add():                                                                       # UC17
    cinemas = q("SELECT * FROM cinemas ORDER BY name")
    if request.method == "POST":
        f = request.form
        name, rtype, cap, cid = f.get("room_name", "").strip(), f.get("room_type"), f.get("capacity", "").strip(), f.get("cinema_id")
        if not (name and rtype in ROOM_TYPES and cap.isdigit() and int(cap) > 0 and cid):
            flash("Vui lòng nhập tên phòng, loại phòng và sức chứa hợp lệ", "danger")
        elif q1("SELECT 1 AS x FROM rooms WHERE cinema_id=%s AND room_name=%s", (cid, name)):
            flash("Tên phòng đã tồn tại", "danger")                                    # 3a
        else:
            rid = ex("INSERT INTO rooms (cinema_id, room_name, room_type, capacity) VALUES (%s,%s,%s,%s)", (cid, name, rtype, int(cap)))
            _build_seats(rid, name, 0, int(cap))
            flash("Thêm phòng chiếu thành công. Hãy cấu hình loại ghế theo vị trí.", "success")
            return redirect(url_for("cinema.room_seats", room_id=rid))
    return render_template("cinema/room_form.html", room=None, cinemas=cinemas, types=ROOM_TYPES)


@bp.route("/manage/rooms/<int:room_id>/edit", methods=["GET", "POST"])
@roles_required(MANAGER)
def room_edit(room_id):                                                               # UC18
    room = q1("SELECT * FROM rooms WHERE room_id=%s", (room_id,))
    if not room:
        return render_template("error.html", code=404, msg="Không tìm thấy phòng chiếu"), 404
    if request.method == "POST":
        f = request.form
        name, rtype, cap = f.get("room_name", "").strip(), f.get("room_type"), f.get("capacity", "").strip()
        status = f.get("status", "ACTIVE")
        if not (name and rtype in ROOM_TYPES and cap.isdigit() and int(cap) > 0):
            flash("Vui lòng nhập đầy đủ thông tin bắt buộc", "danger")                 # 5a
        elif q1("SELECT 1 AS x FROM rooms WHERE cinema_id=%s AND room_name=%s AND room_id<>%s", (room["cinema_id"], name, room_id)):
            flash("Tên phòng đã tồn tại", "danger")
        else:
            cap = int(cap)
            have = q1("SELECT COUNT(*) AS n FROM seats WHERE room_id=%s", (room_id,))["n"]
            if cap > have:
                _build_seats(room_id, name, have, cap)
            # Ghế vượt sức chứa mới -> ngừng sử dụng; ghế trong sức chứa -> hoạt động
            seats = q("SELECT seat_id FROM seats WHERE room_id=%s ORDER BY row_label, seat_number", (room_id,))
            for i, s in enumerate(seats):
                run("UPDATE seats SET is_active=%s WHERE seat_id=%s", (1 if i < cap else 0, s["seat_id"]))
            run("UPDATE rooms SET room_name=%s, room_type=%s, capacity=%s, status=%s WHERE room_id=%s", (name, rtype, cap, status, room_id))
            for st in q("SELECT showtime_id FROM showtimes WHERE room_id=%s AND status='SCHEDULED' AND start_time>=%s", (room_id, sv.now())):
                sync_showtime_seats(st["showtime_id"])
            flash("Cập nhật thông tin phòng chiếu thành công", "success")
            return redirect(url_for("cinema.room_list"))
    return render_template("cinema/room_form.html", room=room, cinemas=q("SELECT * FROM cinemas"), types=ROOM_TYPES)


@bp.route("/manage/rooms/<int:room_id>/stop", methods=["POST"])
@roles_required(MANAGER)
def room_stop(room_id):                                                               # UC19
    n = q1("SELECT COUNT(*) AS n FROM showtimes WHERE room_id=%s AND status='SCHEDULED' AND end_time>=%s", (room_id, sv.now()))["n"]
    if n:
        flash(f"Phòng còn {n} suất chiếu đang hoạt động. Hãy hủy hoặc chuyển các suất chiếu trước khi ngừng sử dụng phòng.", "danger")  # 2a
    else:
        run("UPDATE rooms SET status='INACTIVE' WHERE room_id=%s", (room_id,))
        flash("Phòng chiếu đã chuyển sang trạng thái Ngừng sử dụng", "success")
    return redirect(url_for("cinema.room_list"))


# QLGN - Cấu hình loại ghế (UC21)
@bp.route("/manage/rooms/<int:room_id>/seats", methods=["GET", "POST"])
@roles_required(MANAGER)
def room_seats(room_id):
    room = q1("SELECT r.*, c.name AS cinema FROM rooms r JOIN cinemas c ON c.cinema_id=r.cinema_id WHERE r.room_id=%s", (room_id,))
    if not room:
        return render_template("error.html", code=404, msg="Không tìm thấy phòng chiếu"), 404
    if request.method == "POST":
        ids = [int(x) for x in request.form.getlist("seat_ids")]
        tid = request.form.get("seat_type_id")
        if not ids or not tid:
            flash("Hãy chọn nhóm ghế và loại ghế cần gán", "danger")
        else:
            run("UPDATE seats SET seat_type_id=%s WHERE room_id=%s AND seat_id IN (" + in_clause(ids) + ")", (tid, room_id, *ids))
            flash("Đã lưu cấu hình loại ghế", "success")
        return redirect(url_for("cinema.room_seats", room_id=room_id))
    seats = q("SELECT s.*, st.type_name FROM seats s JOIN seat_types st ON st.seat_type_id=s.seat_type_id "
              "WHERE s.room_id=%s ORDER BY s.row_label, s.seat_number", (room_id,))
    rows = {}
    for s in seats:
        rows.setdefault(s["row_label"], []).append(s)
    return render_template("cinema/room_seats.html", room=room, rows=rows,
                           types=q("SELECT * FROM seat_types ORDER BY seat_type_id"))


#  QLSC - Suất chiếu
def find_conflict(room_id, start, end, exclude_id=None):
    sql = ("SELECT s.showtime_id, s.start_time, s.end_time, m.title FROM showtimes s JOIN movies m ON m.movie_id=s.movie_id "
           "WHERE s.room_id=%s AND s.status='SCHEDULED' AND s.start_time<%s AND s.end_time>%s")
    args = [room_id, end, start]
    if exclude_id:
        sql += " AND s.showtime_id<>%s"
        args.append(exclude_id)
    return q1(sql, tuple(args))


def validate_showtime(movie_id, room_id, start, exclude_id=None):
    """Trả về (movie, room, end, schedule) hoặc ném AppError với đúng thông báo trong báo cáo."""
    movie = q1("SELECT * FROM movies WHERE movie_id=%s", (movie_id,))
    room = q1("SELECT * FROM rooms WHERE room_id=%s", (room_id,))
    if not movie or not room:
        raise sv.AppError("Vui lòng chọn phim và phòng chiếu")
    if movie["status"] == "STOPPED":
        raise sv.AppError("Phim đã ngừng chiếu, không thể thêm suất chiếu")
    if room["status"] != "ACTIVE":
        raise sv.AppError("Phòng chiếu đang ngừng sử dụng")
    end = start + timedelta(minutes=int(movie["duration_min"]))
    c = find_conflict(room_id, start, end, exclude_id)
    if c:
        raise sv.AppError(f"Trùng giờ với suất khác trong cùng phòng: {c['title']} ({sv.to_dt(c['start_time']):%H:%M %d/%m} - "
                          f"{sv.to_dt(c['end_time']):%H:%M})")                          # 3a / xung đột lịch
    same = q1("SELECT status FROM showtimes WHERE room_id=%s AND start_time=%s" + (" AND showtime_id<>%s" if exclude_id else ""),
              (room_id, start, exclude_id) if exclude_id else (room_id, start))
    if same:
        raise sv.AppError("Khung giờ này đã từng được dùng trong phòng (suất đã hủy/đã chiếu), vui lòng chọn giờ khác")
    sch = q1("SELECT * FROM schedules WHERE cinema_id=%s AND start_date<=%s AND end_date>=%s ORDER BY schedule_id LIMIT 1",
             (room["cinema_id"], start.date(), start.date()))
    return movie, room, end, sch


def insert_showtime(schedule_id, movie_id, room_id, start, end):
    sid = ex("INSERT INTO showtimes (schedule_id, movie_id, room_id, start_time, end_time) VALUES (%s,%s,%s,%s,%s)",
             (schedule_id, movie_id, room_id, start, end))
    sync_showtime_seats(sid)
    return sid


def parse_dt(s):
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M")
    except (TypeError, ValueError):
        return None


@bp.route("/showtimes/today")
@roles_required(MANAGER, TICKET_STAFF)
def showtime_today():                                                                 # UC26
    d = request.args.get("date") or date.today().isoformat()
    day = sv.to_date(d)
    rows = q("SELECT s.*, m.title, m.duration_min, r.room_name, r.room_type, c.name AS cinema, "
             "(SELECT COUNT(*) FROM showtime_seats ss WHERE ss.showtime_id=s.showtime_id AND ss.status='SOLD') AS sold, "
             "(SELECT COUNT(*) FROM showtime_seats ss WHERE ss.showtime_id=s.showtime_id) AS total "
             "FROM showtimes s JOIN movies m ON m.movie_id=s.movie_id JOIN rooms r ON r.room_id=s.room_id "
             "JOIN cinemas c ON c.cinema_id=r.cinema_id WHERE s.start_time>=%s AND s.start_time<%s AND s.status='SCHEDULED' "
             "ORDER BY c.name, s.start_time", (datetime(day.year, day.month, day.day), datetime(day.year, day.month, day.day) + timedelta(days=1)))
    return render_template("cinema/showtime_today.html", rows=rows, day=day)


@bp.route("/manage/showtimes")
@roles_required(MANAGER)
def showtime_manage():
    d = request.args.get("date") or date.today().isoformat()
    day = sv.to_date(d)
    lo = datetime(day.year, day.month, day.day)
    rows = q("SELECT s.*, m.title, r.room_name, c.name AS cinema, (SELECT COUNT(*) FROM tickets t WHERE t.showtime_id=s.showtime_id "
             "AND t.status<>'CANCELLED') AS tickets FROM showtimes s JOIN movies m ON m.movie_id=s.movie_id JOIN rooms r ON "
             "r.room_id=s.room_id JOIN cinemas c ON c.cinema_id=r.cinema_id WHERE s.start_time>=%s AND s.start_time<%s "
             "ORDER BY c.name, s.start_time", (lo, lo + timedelta(days=1)))
    return render_template("cinema/showtime_manage.html", rows=rows, day=day,
                           movies=q("SELECT * FROM movies WHERE status<>'STOPPED' ORDER BY title"),
                           rooms=q("SELECT r.*, c.name AS cinema FROM rooms r JOIN cinemas c ON c.cinema_id=r.cinema_id "
                                   "WHERE r.status='ACTIVE' ORDER BY c.name, r.room_name"))


@bp.route("/manage/showtimes/add", methods=["POST"])
@roles_required(MANAGER)
def showtime_add():                                                                   # UC23
    f = request.form
    start = parse_dt(f.get("start_time"))
    back = request.form.get("back") or url_for("cinema.showtime_manage")
    if not (f.get("movie_id") and f.get("room_id") and start):
        flash("Vui lòng chọn phim, phòng chiếu và ngày giờ bắt đầu", "danger")
        return redirect(back)
    movie, room, end, sch = validate_showtime(f["movie_id"], f["room_id"], start)
    if f.get("schedule_id"):
        sch = q1("SELECT * FROM schedules WHERE schedule_id=%s", (f["schedule_id"],))
        if sch and not (sv.to_date(sch["start_date"]) <= start.date() <= sv.to_date(sch["end_date"])):
            raise sv.AppError("Suất chiếu nằm ngoài thời gian của lịch chiếu")
    if not sch:
        raise sv.AppError("Chưa có lịch chiếu bao phủ ngày này. Hãy tạo lịch chiếu tuần/tháng trước.")
    insert_showtime(sch["schedule_id"], movie["movie_id"], room["room_id"], start, end)
    flash("Thêm suất chiếu thành công", "success")
    return redirect(back)


@bp.route("/manage/showtimes/<int:sid>/edit", methods=["GET", "POST"])
@roles_required(MANAGER)
def showtime_edit(sid):                                                               # UC24
    s = q1("SELECT * FROM showtimes WHERE showtime_id=%s", (sid,))
    if not s:
        return render_template("error.html", code=404, msg="Không tìm thấy suất chiếu"), 404
    sold = q1("SELECT COUNT(*) AS n FROM tickets WHERE showtime_id=%s AND status<>'CANCELLED'", (sid,))["n"]
    if request.method == "POST":
        if sold:
            raise sv.AppError("Suất chiếu đã có vé bán, không thể sửa. Hãy hủy/hoàn vé trước.")
        start = parse_dt(request.form.get("start_time"))
        if not (request.form.get("movie_id") and request.form.get("room_id") and start):
            raise sv.AppError("Vui lòng nhập đầy đủ thông tin")
        movie, room, end, sch = validate_showtime(request.form["movie_id"], request.form["room_id"], start, sid)
        if not sch:
            raise sv.AppError("Chưa có lịch chiếu bao phủ ngày này")
        if int(room["room_id"]) != int(s["room_id"]):
            run("DELETE FROM showtime_seats WHERE showtime_id=%s", (sid,))
        run("UPDATE showtimes SET schedule_id=%s, movie_id=%s, room_id=%s, start_time=%s, end_time=%s WHERE showtime_id=%s",
            (sch["schedule_id"], movie["movie_id"], room["room_id"], start, end, sid))
        sync_showtime_seats(sid)
        flash("Cập nhật suất chiếu thành công", "success")
        return redirect(url_for("cinema.showtime_manage", date=start.date().isoformat()))
    return render_template("cinema/showtime_edit.html", s=s, sold=sold,
                           movies=q("SELECT * FROM movies WHERE status<>'STOPPED' ORDER BY title"),
                           rooms=q("SELECT r.*, c.name AS cinema FROM rooms r JOIN cinemas c ON c.cinema_id=r.cinema_id WHERE r.status='ACTIVE'"))


@bp.route("/manage/showtimes/<int:sid>/delete", methods=["POST"])
@roles_required(MANAGER)
def showtime_delete(sid):                                                             # UC25
    s = q1("SELECT * FROM showtimes WHERE showtime_id=%s", (sid,))
    back = request.form.get("back") or url_for("cinema.showtime_manage")
    if not s:
        return redirect(back)
    if q1("SELECT 1 AS x FROM tickets WHERE showtime_id=%s AND status='VALID'", (sid,)):
        flash("Suất chiếu đã có vé bán. Vui lòng xử lý hoàn tiền/hủy vé trước khi xóa.", "danger")   # 2a
    elif q1("SELECT 1 AS x FROM bookings WHERE showtime_id=%s", (sid,)):
        run("UPDATE showtimes SET status='CANCELLED' WHERE showtime_id=%s", (sid,))
        flash("Đã hủy suất chiếu (giữ lại lịch sử đơn hàng)", "success")
    else:
        run("DELETE FROM showtime_seats WHERE showtime_id=%s", (sid,))
        run("DELETE FROM showtimes WHERE showtime_id=%s", (sid,))
        flash("Đã xóa suất chiếu", "success")
    return redirect(back)


#  QLLC - Lịch chiếu
@bp.route("/schedules")
def schedule_view():                                                                  # UC30
    a = request.args
    day = sv.to_date(a.get("date")) if a.get("date") else date.today()
    sql = ("SELECT s.*, m.title, m.age_rating, r.room_name, r.room_type, c.name AS cinema FROM showtimes s "
           "JOIN movies m ON m.movie_id=s.movie_id JOIN rooms r ON r.room_id=s.room_id JOIN cinemas c ON c.cinema_id=r.cinema_id "
           "WHERE s.status='SCHEDULED' AND s.start_time>=%s AND s.start_time<%s")
    lo = datetime(day.year, day.month, day.day)
    args = [lo, lo + timedelta(days=int(a.get("days", 1) or 1))]
    if a.get("cinema"):
        sql += " AND c.cinema_id=%s"
        args.append(a["cinema"])
    if a.get("movie"):
        sql += " AND s.movie_id=%s"
        args.append(a["movie"])
    rows = q(sql + " ORDER BY s.start_time, c.name", tuple(args))
    return render_template("cinema/schedule_view.html", rows=rows, day=day, a=a, cinemas=q("SELECT * FROM cinemas ORDER BY name"),
                           movies=q("SELECT movie_id, title FROM movies WHERE status<>'STOPPED' ORDER BY title"))


@bp.route("/manage/schedules")
@roles_required(MANAGER)
def schedule_list():
    rows = q("SELECT sc.*, c.name AS cinema, (SELECT COUNT(*) FROM showtimes s WHERE s.schedule_id=sc.schedule_id) AS n "
             "FROM schedules sc JOIN cinemas c ON c.cinema_id=sc.cinema_id ORDER BY sc.start_date DESC")
    return render_template("cinema/schedules.html", rows=rows, cinemas=q("SELECT * FROM cinemas ORDER BY name"), today=date.today())


@bp.route("/manage/schedules/add", methods=["POST"])
@roles_required(MANAGER)
def schedule_add():                                                                   # UC27 (bước tạo lịch)
    f = request.form
    try:
        s, e = sv.to_date(f["start_date"]), sv.to_date(f["end_date"])
    except Exception:
        raise sv.AppError("Vui lòng chọn ngày bắt đầu và kết thúc")
    if not (f.get("title", "").strip() and f.get("cinema_id")):
        raise sv.AppError("Vui lòng nhập tên lịch chiếu và chọn rạp")
    if e < s:
        raise sv.AppError("Ngày kết thúc không được trước ngày bắt đầu")
    sid = ex("INSERT INTO schedules (cinema_id, title, period_type, start_date, end_date, created_by) VALUES (%s,%s,%s,%s,%s,%s)",
             (f["cinema_id"], f["title"].strip(), f.get("period_type", "WEEK"), s, e, g.user["user_id"]))
    flash("Đã tạo lịch chiếu. Hãy thêm các suất chiếu.", "success")
    return redirect(url_for("cinema.schedule_detail", sid=sid))


@bp.route("/manage/schedules/<int:sid>")
@roles_required(MANAGER)
def schedule_detail(sid):
    sc = q1("SELECT sc.*, c.name AS cinema FROM schedules sc JOIN cinemas c ON c.cinema_id=sc.cinema_id WHERE sc.schedule_id=%s", (sid,))
    if not sc:
        return render_template("error.html", code=404, msg="Không tìm thấy lịch chiếu"), 404
    shows = q("SELECT s.*, m.title, r.room_name, (SELECT COUNT(*) FROM tickets t WHERE t.showtime_id=s.showtime_id AND t.status='VALID') "
              "AS tickets FROM showtimes s JOIN movies m ON m.movie_id=s.movie_id JOIN rooms r ON r.room_id=s.room_id "
              "WHERE s.schedule_id=%s ORDER BY s.start_time", (sid,))
    return render_template("cinema/schedule_detail.html", sc=sc, shows=shows,
                           movies=q("SELECT * FROM movies WHERE status<>'STOPPED' ORDER BY title"),
                           rooms=q("SELECT * FROM rooms WHERE cinema_id=%s AND status='ACTIVE' ORDER BY room_name", (sc["cinema_id"],)))


@bp.route("/manage/schedules/<int:sid>/bulk", methods=["POST"])
@roles_required(MANAGER)
def schedule_bulk(sid):                                                               # UC27: lên lịch tuần/tháng
    sc = q1("SELECT * FROM schedules WHERE schedule_id=%s", (sid,))
    f = request.form
    days = {int(x) for x in f.getlist("dows")}
    try:
        hh, mm = f.get("time", "").split(":")
        t = (int(hh), int(mm))
    except ValueError:
        raise sv.AppError("Vui lòng nhập giờ chiếu (HH:MM)")
    if not (f.get("movie_id") and f.get("room_id") and days):
        raise sv.AppError("Vui lòng chọn phim, phòng chiếu và các ngày trong tuần")
    added, conflicts = 0, []
    d = sv.to_date(sc["start_date"])
    last = sv.to_date(sc["end_date"])
    while d <= last:
        if d.isoweekday() in days:
            start = datetime(d.year, d.month, d.day, t[0], t[1])
            if start > sv.now():
                try:
                    movie, room, end, _ = validate_showtime(f["movie_id"], f["room_id"], start)
                    insert_showtime(sid, movie["movie_id"], room["room_id"], start, end)
                    added += 1
                except sv.AppError as e:
                    conflicts.append(f"{start:%d/%m %H:%M}: {e}")
        d += timedelta(days=1)
    flash(f"Đã lên lịch {added} suất chiếu.", "success" if added else "warning")
    if conflicts:
        flash("Phát hiện xung đột, đã bỏ qua: " + " | ".join(conflicts[:5]) + (" ..." if len(conflicts) > 5 else ""), "warning")  # 6a
    return redirect(url_for("cinema.schedule_detail", sid=sid))


@bp.route("/manage/schedules/<int:sid>/edit", methods=["POST"])
@roles_required(MANAGER)
def schedule_edit(sid):                                                               # UC28
    f = request.form
    sc = q1("SELECT * FROM schedules WHERE schedule_id=%s", (sid,))
    s, e = sv.to_date(f["start_date"]), sv.to_date(f["end_date"])
    if e < s:
        raise sv.AppError("Ngày kết thúc không được trước ngày bắt đầu")
    out = q1("SELECT COUNT(*) AS n FROM showtimes WHERE schedule_id=%s AND (start_time<%s OR start_time>=%s)",
             (sid, datetime(s.year, s.month, s.day), datetime(e.year, e.month, e.day) + timedelta(days=1)))["n"]
    if out:
        raise sv.AppError(f"Có {out} suất chiếu nằm ngoài khoảng thời gian mới, hãy điều chỉnh trước")
    run("UPDATE schedules SET title=%s, period_type=%s, start_date=%s, end_date=%s WHERE schedule_id=%s",
        (f.get("title", sc["title"]).strip() or sc["title"], f.get("period_type", sc["period_type"]), s, e, sid))
    flash("Cập nhật lịch chiếu thành công", "success")
    return redirect(url_for("cinema.schedule_detail", sid=sid))


@bp.route("/manage/schedules/<int:sid>/delete", methods=["POST"])
@roles_required(MANAGER)
def schedule_delete(sid):                                                             # UC29
    sc = q1("SELECT * FROM schedules WHERE schedule_id=%s", (sid,))
    if sv.to_date(sc["end_date"]) >= date.today():
        raise sv.AppError("Chỉ được xóa lịch chiếu đã qua")
    shows = q("SELECT showtime_id FROM showtimes WHERE schedule_id=%s", (sid,))
    for s in shows:
        if q1("SELECT 1 AS x FROM bookings WHERE showtime_id=%s", (s["showtime_id"],)):
            raise sv.AppError("Lịch chiếu đã có dữ liệu bán vé nên không thể xóa để đảm bảo báo cáo doanh thu")
    for s in shows:
        run("DELETE FROM showtime_seats WHERE showtime_id=%s", (s["showtime_id"],))
        run("DELETE FROM showtimes WHERE showtime_id=%s", (s["showtime_id"],))
    run("DELETE FROM schedules WHERE schedule_id=%s", (sid,))
    flash("Đã xóa lịch chiếu", "success")
    return redirect(url_for("cinema.schedule_list"))


@bp.route("/schedules/export")
@roles_required(MANAGER, TICKET_STAFF)
def schedule_export():                                                                # UC31
    a = request.args
    if not (a.get("from") and a.get("to")):
        return render_template("cinema/schedule_export.html", cinemas=q("SELECT * FROM cinemas ORDER BY name"), a=a, rows=None)
    lo, hi = sv.to_date(a["from"]), sv.to_date(a["to"])
    sql = ("SELECT s.*, m.title, r.room_name, r.room_type, c.name AS cinema FROM showtimes s JOIN movies m ON m.movie_id=s.movie_id "
           "JOIN rooms r ON r.room_id=s.room_id JOIN cinemas c ON c.cinema_id=r.cinema_id WHERE s.status='SCHEDULED' "
           "AND s.start_time>=%s AND s.start_time<%s")
    args = [datetime(lo.year, lo.month, lo.day), datetime(hi.year, hi.month, hi.day) + timedelta(days=1)]
    if a.get("cinema"):
        sql += " AND c.cinema_id=%s"
        args.append(a["cinema"])
    rows = q(sql + " ORDER BY s.start_time, c.name", tuple(args))
    return render_template("cinema/schedule_export.html", cinemas=q("SELECT * FROM cinemas ORDER BY name"), a=a, rows=rows,
                           lo=lo, hi=hi, fmt=a.get("format", "print"))
