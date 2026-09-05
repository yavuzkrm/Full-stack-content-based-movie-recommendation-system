from functools import wraps
from flask import Flask, request, jsonify, render_template, session
import sys, os
import pandas as pd
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config import SECRET_KEY
from user.auth import (register_user, login_user, save_rating,
                       delete_rating, delete_account, add_to_watchlist,
                       remove_from_watchlist, get_watchlist, get_rated_movies, add_to_watched,
                       remove_from_watched, get_watched, add_to_favourites, remove_from_favourites,
                       get_favourites, count_favourites)
from recommend.engine import load_data, recommend, recommend_multi, get_data_and_matrix
from data.fetch_daily_popular_movies import get_popular_movies
from flask_caching import Cache

app = Flask(__name__)
cache = Cache(app, config={'CACHE_TYPE': 'SimpleCache'})
app.secret_key = SECRET_KEY

# A user can only keep 5 movies in their favourites at once — this keeps the
# favourites strip on the homepage small and meaningful instead of turning
# into a second watchlist.
FAVOURITES_LIMIT = 5


def login_required(view_func):
    """Decorator for routes that need a logged-in user. Put @login_required
    right above any route function and it'll automatically reject the request
    with a 401 if nobody's signed in — no need to repeat that check by hand
    in every single route."""
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "You need to be logged in to do that."}), 401
        return view_func(*args, **kwargs)
    return wrapper


# --- JSON-safety helpers -----------------------------------------------------
#
# Some numeric columns (vote_avg, display_rating, weighted_rating) can be
# empty for a movie that has no ratings yet — pandas represents "empty number"
# as NaN. That's normally fine, EXCEPT that Python's built-in json module
# writes NaN out as the bare word `NaN` in the response body, which is not
# actually valid JSON (the JSON spec has no concept of NaN). Browsers refuse
# to parse it: JSON.parse() throws, and the frontend just sees the whole
# request fail with no useful error. We ran into this for real — it made the
# search-as-you-type box randomly show "no results" for certain queries,
# purely because whichever movie happened to be in that response had no
# rating yet. These two helpers convert NaN to Python's None before turning
# anything into JSON, since None correctly becomes JSON's `null`.

def df_to_json_safe(df):
    """Use this instead of jsonify(df.to_dict(...)) for anything built from a
    pandas DataFrame. Note the .astype(object) — without it, pandas silently
    turns our None values right back into NaN, because a plain numeric
    (float64) column literally can't hold a real Python None. Converting to
    the more flexible "object" dtype first is what makes the None stick."""
    safe = df.astype(object).where(pd.notnull(df), None)
    return jsonify(safe.to_dict(orient="records"))


def row_to_json_safe(row_dict):
    """Same idea as df_to_json_safe, but for a single row already turned into
    a plain Python dict (e.g. via df.iloc[0].to_dict())."""
    return jsonify({
        key: (None if isinstance(value, float) and value != value else value)  # `value != value` is a classic (and fast) way to test for NaN, since NaN is the only value in Python that's never equal to itself
        for key, value in row_dict.items()
    })


@app.route("/")
def index():
    return render_template("index.html")


# --- Auth ---------------------------------------------------------------------

@app.route("/api/register", methods=["POST"])
def register():
    data = request.json or {}
    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        return jsonify({"error": "Username and password are required."}), 400

    ok, message = register_user(username, password)
    if ok:
        return jsonify({"message": message}), 201
    return jsonify({"error": message}), 400


@app.route("/api/login", methods=["POST"])
def login():
    data = request.json or {}
    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        return jsonify({"error": "Username and password are required."}), 400

    ok, user_id_or_none, username_or_message = login_user(username, password)
    if not ok:
        return jsonify({"error": username_or_message}), 401

    # Storing the user's id/username in the Flask session means the browser
    # gets a signed cookie back, and every request after this one arrives
    # with that cookie attached — that's how @login_required knows who's
    # asking, without the frontend needing to resend a password every time.
    session["user_id"] = user_id_or_none
    session["username"] = username_or_message
    return jsonify({"user_id": user_id_or_none, "username": username_or_message}), 200


@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"message": "Logged out successfully."}), 200


@app.route("/api/me", methods=["GET"])
def api_me():
    """Lets the frontend ask "is anyone logged in right now, and if so who?"
    when the page first loads, so it can show the right header (login button
    vs. username) without the user having to log in again on every visit."""
    if "user_id" not in session:
        return jsonify({"user": None})
    return jsonify({"user_id": session["user_id"], "username": session["username"]})


@app.route("/api/delete", methods=["DELETE"])
@login_required
def delete():
    ok, message = delete_account(session["user_id"])
    if ok:
        session.clear()
        return jsonify({"message": message}), 200
    return jsonify({"error": message}), 404


# --- Recommendations & search ---------------------------------------------

@app.route("/api/recommend")
def recommend_movies():
    title = request.args.get("title")
    top_n = request.args.get("top_n", default=10, type=int)

    if not title:
        return jsonify({"error": "A 'title' query parameter is required."}), 400

    results = recommend(title, top_n)
    return df_to_json_safe(results), 200


@app.route("/api/recommend_multi", methods=["POST"])
def recommend_movies_multi():
    data = request.json or {}
    titles = data.get("titles", [])
    top_n = data.get("top_n", 10)

    if not titles or not isinstance(titles, list) or not (2 <= len(titles) <= 5):
        return jsonify({"error": "'titles' must be a list of 2 to 5 movie titles."}), 400

    results = recommend_multi(titles, top_n)
    return df_to_json_safe(results), 200


@app.route("/api/search")
def api_search():
    """Powers the search-as-you-type box. Matches any movie whose title
    CONTAINS the query, then sorts so that titles STARTING WITH the query
    show up first (typing "int" should surface "Interstellar" before some
    movie that merely mentions "interior" in the middle of its title), and
    breaks any remaining ties by rating."""
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify([])

    df = load_data()
    q_lower = q.lower()
    title_lower = df["title"].str.lower()

    mask = title_lower.str.contains(q_lower, regex=False)
    matches = df[mask].copy()

    matches["_starts_with"] = title_lower[mask].str.startswith(q_lower).values
    matches = matches.sort_values(by=["_starts_with", "display_rating"], ascending=[False, False])

    cols = ["id", "title", "poster_path", "display_rating"]
    return df_to_json_safe(matches[cols].head(8))


@app.route("/api/movie/<int:movie_id>")
def api_get_movie(movie_id):
    """Full details for a single movie (overview, genres, cast, ...) — used
    whenever the frontend already has a "lightweight" movie object (e.g. from
    /api/search, which only returns title/poster/rating) and needs the rest
    of the details to show a detail view."""
    df = load_data()
    row = df[df["id"] == movie_id]
    if row.empty:
        return jsonify({}), 404
    return row_to_json_safe(row.iloc[0].to_dict())


# --- Ratings -------------------------------------------------------------

@app.route("/api/rating/<int:movie_id>", methods=["POST"])
@login_required
def api_save_rating(movie_id):
    data = request.json or {}
    rating = data.get("rating")
    if rating is None or not (1 <= float(rating) <= 10):
        return jsonify({"error": "Rating must be between 1 and 10."}), 400

    save_rating(session["user_id"], movie_id, rating)
    return jsonify({"message": "Rating saved."})


@app.route("/api/rating/<int:movie_id>", methods=["DELETE"])
@login_required
def api_delete_rating(movie_id):
    delete_rating(session["user_id"], movie_id)
    return jsonify({"message": "Rating removed."})


@app.route("/api/ratings")
@login_required
def api_get_rated_movies():
    return jsonify(get_rated_movies(session["user_id"]))


# --- Watched ---------------------------------------------------------------

@app.route("/api/watched/<int:movie_id>", methods=["POST"])
@login_required
def api_add_watched(movie_id):
    add_to_watched(session["user_id"], movie_id)
    return jsonify({"message": "Added to watched."})


@app.route("/api/watched/<int:movie_id>", methods=["DELETE"])
@login_required
def api_remove_watched(movie_id):
    remove_from_watched(session["user_id"], movie_id)
    return jsonify({"message": "Removed from watched."})


@app.route("/api/watched")
@login_required
def api_get_watched():
    return jsonify(get_watched(session["user_id"]))


# --- Watchlist ---------------------------------------------------------------

@app.route("/api/watchlist/<int:movie_id>", methods=["POST"])
@login_required
def api_add_watchlist(movie_id):
    add_to_watchlist(session["user_id"], movie_id)
    return jsonify({"message": "Added to watchlist."})


@app.route("/api/watchlist/<int:movie_id>", methods=["DELETE"])
@login_required
def api_remove_watchlist(movie_id):
    remove_from_watchlist(session["user_id"], movie_id)
    return jsonify({"message": "Removed from watchlist."})


@app.route("/api/watchlist")
@login_required
def api_get_watchlist():
    return jsonify(get_watchlist(session["user_id"]))


# --- Favourites ---------------------------------------------------------------

@app.route("/api/favourites/<int:movie_id>", methods=["POST"])
@login_required
def api_add_favourite(movie_id):
    # We only need a COUNT here, not the favourite movies' full details — using
    # count_favourites() (a plain "SELECT COUNT(*)") instead of fetching the
    # whole list with all its genre/cast/director joins is what fixed the
    # noticeable delay this button used to have on every click.
    if count_favourites(session["user_id"]) >= FAVOURITES_LIMIT:
        return jsonify({"error": f"Your favourites list is full (max {FAVOURITES_LIMIT})."}), 409

    add_to_favourites(session["user_id"], movie_id)
    return jsonify({"message": "Added to favourites."})


@app.route("/api/favourites/<int:movie_id>", methods=["DELETE"])
@login_required
def api_remove_favourite(movie_id):
    remove_from_favourites(session["user_id"], movie_id)
    return jsonify({"message": "Removed from favourites."})


@app.route("/api/favourites")
@login_required
def api_get_favourites():
    return jsonify(get_favourites(session["user_id"]))


# --- Popular today ---------------------------------------------------------

@app.route("/api/popular")
@cache.cached(timeout=86400)  # cache the response for 24 hours — the trending list only changes once a day anyway (see refresh_popular_movies below), so there's no reason to hit the database on every single visitor
def api_get_popular_movies():
    return jsonify(get_popular_movies())

# --- Warm up the recommendation engine on startup -----------------------------
try:
    get_data_and_matrix()
    print("Recommendation engine ready.")
except Exception as e:
    print(f"Could not warm up the recommendation engine (will retry on first search): {e}")
