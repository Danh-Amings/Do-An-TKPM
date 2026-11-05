"""QLP: UC06-UC11 (phim) · QLTL: UC12-UC15 (thể loại)"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, g

from ..db import q, q1, ex, run, in_clause
from ..security import roles_required, MANAGER, login_required
from .. import services as sv
from .auth import save_upload

bp = Blueprint("movies", __name__)

AGE_RATINGS = ["P", "K", "T13", "T16", "T18"]
STATUS_LABEL = {"NOW_SHOWING": "Đang chiếu", "COMING_SOON": "Sắp chiếu", "STOPPED": "Ngừng chiếu"}


def attach_genres(movies):
    if not movies:
        return movies
    ids = [m["movie_id"] for m in movies]
    rows = q("SELECT mg.movie_id, g.genre_id, g.genre_name FROM movie_genres mg JOIN genres g ON g.genre_id=mg.genre_id "
             "WHERE mg.movie_id IN (" + in_clause(ids) + ") ORDER BY g.genre_name", tuple(ids))
    by = {}
    for r in rows:
        by.setdefault(r["movie_id"], []).append(r)
    for m in movies:
        m["genres"] = by.get(m["movie_id"], [])
    return movies


# ------------------------------------------------------------------ UC06 Xem danh sách phim
@bp.route("/movies")
def movie_list():
    status = request.args.get("status", "")
    sql, args = "SELECT * FROM movies WHERE status<>'STOPPED'", []
    if status in ("NOW_SHOWING", "COMING_SOON"):
        sql += " AND status=%s"
        args.append(status)
    movies = attach_genres(q(sql + " ORDER BY status DESC, release_date DESC, title", tuple(args)))
    return render_template("movies/list.html", movies=movies, status=status, STATUS_LABEL=STATUS_LABEL)


# ------------------------------------------------------------------ UC07 Tìm kiếm phim
def search_movies(kw="", genre_id="", year="", age="", cinema_id="", city=""):
    sql = "SELECT m.* FROM movies m WHERE m.status<>'STOPPED'"
    args = []
    if kw:
        like = f"%{kw}%"
        sql += (" AND (m.title LIKE %s OR m.cast_list LIKE %s OR m.director LIKE %s OR EXISTS (SELECT 1 FROM movie_genres mg "
                "JOIN genres g ON g.genre_id=mg.genre_id WHERE mg.movie_id=m.movie_id AND g.genre_name LIKE %s))")
        args += [like, like, like, like]
    if genre_id:
        sql += " AND EXISTS (SELECT 1 FROM movie_genres mg WHERE mg.movie_id=m.movie_id AND mg.genre_id=%s)"
        args.append(genre_id)
    if year:
        sql += " AND m.release_year=%s"
        args.append(year)
    if age:
        sql += " AND m.age_rating=%s"
        args.append(age)
    if cinema_id or city:
        sql += (" AND EXISTS (SELECT 1 FROM showtimes s JOIN rooms r ON r.room_id=s.room_id JOIN cinemas c ON c.cinema_id=r.cinema_id "
                "WHERE s.movie_id=m.movie_id AND s.status='SCHEDULED' AND s.start_time>=%s")
        args.append(sv.now())
        if cinema_id:
            sql += " AND c.cinema_id=%s"
            args.append(cinema_id)
        if city:
            sql += " AND c.city=%s"
            args.append(city)
        sql += ")"
    return attach_genres(q(sql + " ORDER BY m.status DESC, m.title", tuple(args)))


@bp.route("/movies/search")
def movie_search():
    a = request.args
    kw = a.get("q", "").strip()
    searched = any(a.get(k) for k in ("q", "genre", "year", "age", "cinema", "city"))
    movies = search_movies(kw, a.get("genre", ""), a.get("year", ""), a.get("age", ""), a.get("cinema", ""), a.get("city", "")) \
        if searched else []
    suggestions = q("SELECT * FROM movies WHERE status IN ('NOW_SHOWING','COMING_SOON') ORDER BY status DESC, avg_rating DESC LIMIT 6")
    return render_template("movies/search.html", movies=movies, searched=searched, kw=kw, a=a, suggestions=suggestions,
                           genres=q("SELECT * FROM genres ORDER BY genre_name"), cinemas=q("SELECT * FROM cinemas ORDER BY name"),
                           cities=q("SELECT DISTINCT city FROM cinemas ORDER BY city"), ages=AGE_RATINGS)


@bp.route("/api/movies/suggest")
def movie_suggest():
    """Gợi ý (autocomplete) theo thời gian thực"""
    kw = request.args.get("q", "").strip()
    if not kw:
        return jsonify([])
    like = f"%{kw}%"
    rows = q("SELECT movie_id, title, release_year FROM movies WHERE status<>'STOPPED' AND (title LIKE %s OR cast_list LIKE %s) "
             "ORDER BY title LIMIT 8", (like, like))
    return jsonify([dict(id=r["movie_id"], title=r["title"], year=r["release_year"]) for r in rows])


# ------------------------------------------------------------------ UC08 Chi tiết phim
@bp.route("/movies/<int:movie_id>")
def movie_detail(movie_id):
    m = q1("SELECT * FROM movies WHERE movie_id=%s", (movie_id,))
    if not m:
        return render_template("error.html", code=404, msg="Không tìm thấy phim"), 404
    attach_genres([m])
    shows = []
    if m["status"] != "STOPPED":
        shows = q("SELECT s.showtime_id, s.start_time, s.end_time, r.room_name, r.room_type, c.name AS cinema, c.cinema_id, "
                  "(SELECT COUNT(*) FROM showtime_seats ss WHERE ss.showtime_id=s.showtime_id AND ss.status='AVAILABLE') AS free_seats "
                  "FROM showtimes s JOIN rooms r ON r.room_id=s.room_id JOIN cinemas c ON c.cinema_id=r.cinema_id "
                  "WHERE s.movie_id=%s AND s.status='SCHEDULED' AND s.start_time>=%s ORDER BY c.name, s.start_time",
                  (movie_id, sv.now()))
    grouped = {}
    for s in shows:
        day = sv.to_dt(s["start_time"]).date()
        grouped.setdefault(s["cinema"], {}).setdefault(day, []).append(s)
    return render_template("movies/detail.html", m=m, grouped=grouped, STATUS_LABEL=STATUS_LABEL)


# ------------------------------------------------------------------ Quản lý phim (Quản lý rạp)
@bp.route("/manage/movies")
@roles_required(MANAGER)
def manage_movies():
    rows = attach_genres(q("SELECT m.*, (SELECT COUNT(*) FROM showtimes s WHERE s.movie_id=m.movie_id AND s.status='SCHEDULED' "
                           "AND s.start_time>=%s) AS active_shows FROM movies m ORDER BY m.movie_id DESC", (sv.now(),)))
    return render_template("movies/manage.html", rows=rows, STATUS_LABEL=STATUS_LABEL)


def _movie_form_data():
    f = request.form
    return dict(
        title=f.get("title", "").strip(), release_year=f.get("release_year", "").strip(),
        age_rating=f.get("age_rating", ""), duration_min=f.get("duration_min", "").strip(),
        director=f.get("director", "").strip(), cast_list=f.get("cast_list", "").strip(),
        description=f.get("description", "").strip(), trailer_url=f.get("trailer_url", "").strip(),
        release_date=f.get("release_date") or None, status=f.get("status", "COMING_SOON"),
        poster_url=f.get("poster_url", "").strip(), genres=[int(x) for x in f.getlist("genres")],
        distributor_id=f.get("distributor_id") or "", share_percent=f.get("share_percent", "").strip(),
    )


def _validate_movie(d):
    if not (d["title"] and d["release_year"] and d["age_rating"] and d["duration_min"] and d["genres"]):
        return "Vui lòng nhập đầy đủ thông tin bắt buộc"
    if not (d["release_year"].isdigit() and d["duration_min"].isdigit() and int(d["duration_min"]) > 0):
        return "Năm sản xuất và thời lượng phải là số hợp lệ"
    return None


def _save_distributor(movie_id, d):
    run("DELETE FROM distributor_contracts WHERE movie_id=%s", (movie_id,))
    if d["distributor_id"]:
        try:
            pct = float(d["share_percent"] or 0)
        except ValueError:
            pct = -1
        if not 0 <= pct <= 100:
            raise sv.AppError("Tỷ lệ chia sẻ doanh thu phải từ 0 đến 100")
        ex("INSERT INTO distributor_contracts (movie_id, distributor_id, share_percent) VALUES (%s,%s,%s)",
           (movie_id, d["distributor_id"], pct))


def _form_ctx(d, movie=None):
    return dict(d=d, movie=movie, genres=q("SELECT * FROM genres ORDER BY genre_name"), ages=AGE_RATINGS,
                distributors=q("SELECT * FROM distributors ORDER BY name"), STATUS_LABEL=STATUS_LABEL)


# ------------------------------------------------------------------ UC09 Thêm phim mới
@bp.route("/manage/movies/add", methods=["GET", "POST"])
@roles_required(MANAGER)
def movie_add():
    if request.method == "POST":
        d = _movie_form_data()
        err = _validate_movie(d)
        if not err and q1("SELECT 1 AS x FROM movies WHERE title=%s AND release_year=%s", (d["title"], d["release_year"])):
            err = "Phim đã tồn tại"                                                  # 5b
        if err:
            flash(err, "danger")
            return render_template("movies/form.html", **_form_ctx(d))
        file = request.files.get("poster")
        if file and file.filename:
            d["poster_url"] = save_upload(file, "posters", "poster")
        mid = ex("INSERT INTO movies (title, release_year, age_rating, duration_min, director, cast_list, description, poster_url, "
                 "trailer_url, release_date, status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                 (d["title"], d["release_year"], d["age_rating"], d["duration_min"], d["director"], d["cast_list"],
                  d["description"], d["poster_url"] or None, d["trailer_url"] or None, d["release_date"], d["status"]))
        for gid in d["genres"]:
            ex("INSERT INTO movie_genres (movie_id, genre_id) VALUES (%s,%s)", (mid, gid))
        _save_distributor(mid, d)
        flash("Thêm phim thành công", "success")
        return redirect(url_for("movies.manage_movies"))
    return render_template("movies/form.html", **_form_ctx(dict(genres=[], status="COMING_SOON")))


# ------------------------------------------------------------------ UC10 Cập nhật thông tin phim
@bp.route("/manage/movies/<int:movie_id>/edit", methods=["GET", "POST"])
@roles_required(MANAGER)
def movie_edit(movie_id):
    m = q1("SELECT * FROM movies WHERE movie_id=%s", (movie_id,))
    if not m:
        return render_template("error.html", code=404, msg="Không tìm thấy phim"), 404
    if request.method == "POST":
        d = _movie_form_data()
        err = _validate_movie(d)
        if not err and q1("SELECT 1 AS x FROM movies WHERE title=%s AND release_year=%s AND movie_id<>%s",
                          (d["title"], d["release_year"], movie_id)):
            err = "Phim đã tồn tại"
        if err:
            flash(err, "danger")
            return render_template("movies/form.html", **_form_ctx(d, m))
        file = request.files.get("poster")
        poster = d["poster_url"] or m["poster_url"]
        if file and file.filename:
            poster = save_upload(file, "posters", "poster")
        run("UPDATE movies SET title=%s, release_year=%s, age_rating=%s, duration_min=%s, director=%s, cast_list=%s, "
            "description=%s, poster_url=%s, trailer_url=%s, release_date=%s, status=%s WHERE movie_id=%s",
            (d["title"], d["release_year"], d["age_rating"], d["duration_min"], d["director"], d["cast_list"], d["description"],
             poster, d["trailer_url"] or None, d["release_date"], d["status"], movie_id))
        run("DELETE FROM movie_genres WHERE movie_id=%s", (movie_id,))
        for gid in d["genres"]:
            ex("INSERT INTO movie_genres (movie_id, genre_id) VALUES (%s,%s)", (movie_id, gid))
        _save_distributor(movie_id, d)
        flash("Cập nhật phim thành công", "success")
        return redirect(url_for("movies.manage_movies"))
    gids = [r["genre_id"] for r in q("SELECT genre_id FROM movie_genres WHERE movie_id=%s", (movie_id,))]
    ct = q1("SELECT * FROM distributor_contracts WHERE movie_id=%s", (movie_id,))
    d = dict(m, genres=gids, distributor_id=ct["distributor_id"] if ct else "", share_percent=ct["share_percent"] if ct else "",
             release_year=str(m["release_year"]), duration_min=str(m["duration_min"]))
    return render_template("movies/form.html", **_form_ctx(d, m))


# ------------------------------------------------------------------ UC11 Ngừng chiếu / Xóa phim
def _active_shows(movie_id):
    return q1("SELECT COUNT(*) AS n FROM showtimes WHERE movie_id=%s AND status='SCHEDULED' AND end_time>=%s",
              (movie_id, sv.now()))["n"]


@bp.route("/manage/movies/<int:movie_id>/stop", methods=["POST"])
@roles_required(MANAGER)
def movie_stop(movie_id):
    # Báo cáo UC11 (3a): còn suất chiếu hoạt động -> chỉ được "Ngừng chiếu", không được Xóa
    run("UPDATE movies SET status='STOPPED' WHERE movie_id=%s", (movie_id,))
    flash("Đã chuyển phim sang trạng thái Ngừng chiếu", "success")
    return redirect(url_for("movies.manage_movies"))


@bp.route("/manage/movies/<int:movie_id>/delete", methods=["POST"])
@roles_required(MANAGER)
def movie_delete(movie_id):
    if _active_shows(movie_id):
        flash("Không thể xóa phim còn suất chiếu đang hoạt động, vui lòng chuyển trạng thái Ngừng chiếu trước.", "danger")  # 3a
    elif q1("SELECT 1 AS x FROM showtimes WHERE movie_id=%s", (movie_id,)):
        flash("Phim đã có lịch sử suất chiếu/vé nên không thể xóa hẳn. Hãy dùng Ngừng chiếu.", "warning")
    else:
        run("DELETE FROM distributor_contracts WHERE movie_id=%s", (movie_id,))
        run("DELETE FROM movies WHERE movie_id=%s", (movie_id,))
        flash("Đã xóa phim", "success")
    return redirect(url_for("movies.manage_movies"))


# ================================================================== QLTL
@bp.route("/manage/genres")
@roles_required(MANAGER)
def genre_list():                                                                    # UC12
    rows = q("SELECT g.*, (SELECT COUNT(*) FROM movie_genres mg WHERE mg.genre_id=g.genre_id) AS n FROM genres g ORDER BY genre_name")
    return render_template("movies/genres.html", rows=rows, edit=request.args.get("edit", type=int))


@bp.route("/manage/genres/add", methods=["POST"])
@roles_required(MANAGER)
def genre_add():                                                                     # UC13
    name = request.form.get("genre_name", "").strip()
    if not name:
        flash("Vui lòng nhập tên thể loại", "danger")
    elif q1("SELECT 1 AS x FROM genres WHERE genre_name=%s", (name,)):
        flash("Thể loại đã tồn tại", "danger")                                       # 5a
    else:
        ex("INSERT INTO genres (genre_name) VALUES (%s)", (name,))
        flash("Thêm thể loại thành công", "success")
    return redirect(url_for("movies.genre_list"))


@bp.route("/manage/genres/<int:gid>/edit", methods=["POST"])
@roles_required(MANAGER)
def genre_edit(gid):                                                                 # UC14
    name = request.form.get("genre_name", "").strip()
    if not name:
        flash("Vui lòng nhập tên thể loại", "danger")
    elif q1("SELECT 1 AS x FROM genres WHERE genre_name=%s AND genre_id<>%s", (name, gid)):
        flash("Thể loại đã tồn tại", "danger")
    else:
        run("UPDATE genres SET genre_name=%s WHERE genre_id=%s", (name, gid))
        flash("Cập nhật thể loại thành công", "success")
    return redirect(url_for("movies.genre_list"))


@bp.route("/manage/genres/<int:gid>/delete", methods=["POST"])
@roles_required(MANAGER)
def genre_delete(gid):                                                               # UC15
    if q1("SELECT 1 AS x FROM movie_genres WHERE genre_id=%s", (gid,)):
        flash("Không thể xóa thể loại đang có phim liên kết", "danger")              # 3a
    else:
        run("DELETE FROM genres WHERE genre_id=%s", (gid,))
        flash("Đã xóa thể loại", "success")
    return redirect(url_for("movies.genre_list"))
