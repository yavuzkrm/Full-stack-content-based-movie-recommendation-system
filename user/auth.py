import string
import mysql.connector
from werkzeug.security import generate_password_hash, check_password_hash  # for turning a plain-text password into a secure hash, and checking a login attempt against that hash
from config import cnxpool  # the shared connection pool set up in config.py

# Quick cheat sheet for cursor.execute() results, since it trips people up the
# first time they use mysql-connector:
#   cursor.execute(...)      -> runs the query, doesn't give you the data back directly
#   cursor.fetchone()        -> one row, e.g. ("alice", "hash123")            (a tuple)
#   cursor.fetchall()        -> every row, as a list of tuples
#   cursor.fetchmany(n)      -> just the next n rows
# When we open the cursor with dictionary=True, rows come back as
# {"column_name": value} instead of a plain tuple — much easier to read.


def get_db():
    """Borrows one ready-to-use connection from the pool (see config.py).
    Always closed again in a `finally` block wherever it's used, so it goes
    straight back into the pool for the next request to reuse."""
    return cnxpool.get_connection()


def check_password(password):
    """
    Checks a candidate password against our signup rules. Returns
    (True, "ok message") if it passes, or (False, "what's wrong") if not —
    that message is shown directly to the user, so keep it friendly.
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters long."
    if not any(c.isdigit() for c in password):
        return False, "Password must contain at least one digit."
    if not any(c.isupper() for c in password):
        return False, "Password must contain at least one uppercase letter."
    if not any(c.islower() for c in password):
        return False, "Password must contain at least one lowercase letter."
    if not any(c in string.punctuation for c in password):
        return False, "Password must contain at least one special character."
    if any(c.isspace() for c in password):
        return False, "Password cannot contain spaces."
    return True, "Password is valid."


def register_user(username, password):
    """Creates a new account. Returns (True, message) on success or
    (False, message) if the password is invalid or the username is taken."""
    is_valid, message = check_password(password)
    if not is_valid:
        return False, message

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO users (username, password_hash) VALUES (%s, %s)",
            (username, generate_password_hash(password))
        )
        conn.commit()
        return True, "Account created successfully!"
    except mysql.connector.IntegrityError:
        # This fires when the INSERT violates the `username UNIQUE` rule in
        # the schema — i.e. someone already has this username.
        return False, "That username is already taken."
    finally:
        cursor.close()
        conn.close()


def login_user(username, password):
    """Checks a username/password pair. Returns (True, user_id, username) on
    success, or (False, None, error_message) if the login fails."""
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT id, username, password_hash FROM users WHERE username=%s",
            (username,)
        )
        user = cursor.fetchone()
        if user and check_password_hash(user["password_hash"], password):
            return True, user["id"], user["username"]
        return False, None, "Incorrect username or password."
    except Exception as e:
        print(f"Login error: {e}")
        return False, None, "Something went wrong, please try again."
    finally:
        cursor.close()
        conn.close()


def delete_account(user_id):
    """Permanently deletes a user account. Every row that references this
    user (ratings, watchlist, favourites, ...) disappears with it automatically
    thanks to "ON DELETE CASCADE" in the schema — we don't have to clean those
    up by hand here."""
    conn = get_db()
    cursor = conn.cursor()
    deleted_rows = 0
    try:
        cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()
        deleted_rows = cursor.rowcount
    except Exception as e:
        print(f"Account deletion error: {e}")
        return False, "Something went wrong while deleting the account."
    finally:
        cursor.close()
        conn.close()
    if deleted_rows == 0:
        return False, "User not found."
    return True, "Account deleted successfully."


# --- Ratings -----------------------------------------------------------------

def save_rating(user_id, movie_id, rating):
    """Records a user's rating for a movie. If they've already rated it, this
    just updates the existing score instead of creating a second row — that's
    what "ON DUPLICATE KEY UPDATE" does, and it works because (user_id, movie_id)
    is the table's primary key, so MySQL already knows it's the "same" row."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO user_ratings (user_id, movie_id, rating) VALUES (%s, %s, %s) "
            "ON DUPLICATE KEY UPDATE rating = %s",
            (user_id, movie_id, rating, rating)
        )
        conn.commit()
    except Exception as e:
        print(f"Error saving rating: {e}")
    finally:
        cursor.close()
        conn.close()


def delete_rating(user_id, movie_id):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "DELETE FROM user_ratings WHERE user_id = %s AND movie_id = %s",
            (user_id, movie_id)
        )
        conn.commit()
    except Exception as e:
        print(f"Error deleting rating: {e}")
    finally:
        cursor.close()
        conn.close()


def get_rated_movies(user_id):
    """Every movie a user has rated, most recent first, with full movie
    details (poster, genres, director, cast) alongside the score they gave it —
    everything the "Your ratings" page on the frontend needs in one request."""
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT
                m.id, m.title, m.poster_path, m.overview, m.vote_avg, ur.rating,
                GROUP_CONCAT(DISTINCT g.name SEPARATOR ',') AS genres,
                GROUP_CONCAT(DISTINCT pd.name SEPARATOR ', ') AS directors,
                GROUP_CONCAT(DISTINCT pc.name SEPARATOR ', ') AS cast
            FROM user_ratings ur
            JOIN movies m ON ur.movie_id = m.id
            LEFT JOIN movie_genres mg ON mg.movie_id = m.id
            LEFT JOIN genres g ON g.id = mg.genre_id
            LEFT JOIN movie_directors md ON md.movie_id = m.id
            LEFT JOIN people pd ON pd.id = md.person_id
            LEFT JOIN movie_cast mc ON mc.movie_id = m.id
            LEFT JOIN people pc ON pc.id = mc.person_id
            WHERE ur.user_id = %s
            GROUP BY m.id, m.title, m.poster_path, m.overview, m.vote_avg, ur.rating
            ORDER BY ur.rated_at DESC
        """, (user_id,))
        return cursor.fetchall()
    except Exception as e:
        print(f"Error fetching rated movies: {e}")
        return []
    finally:
        cursor.close()
        conn.close()


# --- Watchlist / Watched / Favourites ----------------------------------------
#
# These three lists (watchlist, watched, favourites) are all structurally
# identical: a table with just (user_id, movie_id, added_at), and the exact
# same "add a row" / "remove a row" / "list them with full movie details"
# operations. Rather than write that logic three times over (which is exactly
# what this file used to do — nine nearly-identical functions), we write it
# ONCE as a private helper below and have each list's public function just
# call it with its own table name. If we ever need to change how any of this
# works, there's only one place to fix it instead of three.
#
# Table names below are only ever one of our own hardcoded constants — never
# something a user typed in — so building the SQL string with an f-string here
# is safe. (If a table name could ever come from user input, this pattern
# would be a SQL-injection risk and you'd need to validate it against an
# allow-list first.)

def _add_to_list(table, user_id, movie_id):
    conn = get_db()
    cursor = conn.cursor()
    try:
        # INSERT IGNORE: if this (user_id, movie_id) pair is already in the
        # table, MySQL just silently skips the insert instead of raising a
        # duplicate-key error — exactly what we want for an "add" action that
        # might get clicked twice.
        cursor.execute(
            f"INSERT IGNORE INTO {table} (user_id, movie_id) VALUES (%s, %s)",
            (user_id, movie_id)
        )
        conn.commit()
    except Exception as e:
        print(f"Error adding to {table}: {e}")
    finally:
        cursor.close()
        conn.close()


def _remove_from_list(table, user_id, movie_id):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"DELETE FROM {table} WHERE user_id = %s AND movie_id = %s",
            (user_id, movie_id)
        )
        conn.commit()
    except Exception as e:
        print(f"Error removing from {table}: {e}")
    finally:
        cursor.close()
        conn.close()


def _get_list_with_movie_details(table, user_id, order_direction="DESC"):
    """Fetches every movie in the given list table for this user, joined up
    with its genres/director/cast so the frontend can render a full card
    without a second request per movie. `order_direction` is always one of
    our own hardcoded "ASC"/"DESC" strings (never user input), so — same as
    the table name above — it's safe to drop straight into the query."""
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(f"""
            SELECT
                m.id, m.title, m.poster_path, m.overview, m.vote_avg,
                GROUP_CONCAT(DISTINCT g.name SEPARATOR ',') AS genres,
                GROUP_CONCAT(DISTINCT pd.name SEPARATOR ', ') AS directors,
                GROUP_CONCAT(DISTINCT pc.name SEPARATOR ', ') AS cast
            FROM {table} w
            JOIN movies m ON w.movie_id = m.id
            LEFT JOIN movie_genres mg ON mg.movie_id = m.id
            LEFT JOIN genres g ON g.id = mg.genre_id
            LEFT JOIN movie_directors md ON md.movie_id = m.id
            LEFT JOIN people pd ON pd.id = md.person_id
            LEFT JOIN movie_cast mc ON mc.movie_id = m.id
            LEFT JOIN people pc ON pc.id = mc.person_id
            WHERE w.user_id = %s
            GROUP BY m.id, m.title, m.poster_path, m.overview, m.vote_avg
            ORDER BY w.added_at {order_direction}
        """, (user_id,))
        return cursor.fetchall()
    except Exception as e:
        print(f"Error fetching {table}: {e}")
        return []
    finally:
        cursor.close()
        conn.close()


def _count_list(table, user_id):
    """A lightweight row-count for a list table — used where we only need to
    know HOW MANY movies are in a list (e.g. enforcing the 5-favourite limit),
    not the movies themselves. This deliberately skips every JOIN that
    _get_list_with_movie_details does, because pulling genres/cast/director
    for every favourite just to count them was pure waste — and was actually
    slowing down the "add to favourites" button noticeably before this
    function existed."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE user_id = %s", (user_id,))
        return cursor.fetchone()[0]
    except Exception as e:
        print(f"Error counting {table}: {e}")
        return 0
    finally:
        cursor.close()
        conn.close()


def add_to_watchlist(user_id, movie_id):
    _add_to_list("user_watchlist", user_id, movie_id)


def remove_from_watchlist(user_id, movie_id):
    _remove_from_list("user_watchlist", user_id, movie_id)


def get_watchlist(user_id):
    return _get_list_with_movie_details("user_watchlist", user_id, "DESC")


def add_to_watched(user_id, movie_id):
    _add_to_list("user_watched", user_id, movie_id)


def remove_from_watched(user_id, movie_id):
    _remove_from_list("user_watched", user_id, movie_id)


def get_watched(user_id):
    return _get_list_with_movie_details("user_watched", user_id, "DESC")


def add_to_favourites(user_id, movie_id):
    _add_to_list("user_favourites", user_id, movie_id)


def remove_from_favourites(user_id, movie_id):
    _remove_from_list("user_favourites", user_id, movie_id)


def get_favourites(user_id):
    # Favourites are shown oldest-first (ASC) on purpose: the frontend adds a
    # newly-favourited movie to the END of the strip it displays, so fetching
    # them in the same oldest-to-newest order means the list never visibly
    # "jumps around" after a page refresh.
    return _get_list_with_movie_details("user_favourites", user_id, "ASC")


def count_favourites(user_id):
    return _count_list("user_favourites", user_id)
