from flask import Blueprint, render_template, g, redirect, url_for

from ..db import q
from .. import services as sv

bp = Blueprint("main", __name__)


@bp.route("/")
def home():
    movies = q("SELECT * FROM movies WHERE status IN ('NOW_SHOWING','COMING_SOON') ORDER BY status DESC, release_date DESC LIMIT 8")
    return render_template("home.html", movies=movies)
