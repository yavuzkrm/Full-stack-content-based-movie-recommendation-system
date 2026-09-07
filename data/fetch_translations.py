import sys
import os
import time
import requests
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from config import TMDB_API_KEY, TMDB_BASE_URL, cnxpool

# Run this by hand, once, after adding the title_tr/overview_tr/name_tr
# columns (see the migration note at the bottom of db/schema.sql):
#
#   python -m data.fetch_translations
#
# It's SAFE to run again later, as often as you like — both functions below
# only ever touch rows that are still missing a translation (WHERE title_tr
# IS NULL / WHERE name_tr IS NULL), so re-running this after adding new
# movies to the catalogue only fetches translations for the NEW ones, never
# re-fetches ones it already has.
#
# You don't actually need to remember to run this by hand on a schedule,
# though: data/fetch_daily_popular_movies.py calls fetch_and_save_movie_translation()
# (see below) for every movie in each day's "Trending Today" refresh, so any
# movie that enters the catalogue that way gets translated automatically as
# part of the daily job. This script is for the one-off bulk catch-up
# (translating whatever's already in the catalogue before that started
# happening) — not something that needs to keep running forever by hand.


def get_db():
    return cnxpool.get_connection()


def fetch_and_save_genre_translations():
    """Turkish names for TMDB's fixed genre list — a single API call handles
    every genre at once (there are only ~19 of them), so unlike movies below
    this doesn't need a per-row loop or a IS-NULL check to stay cheap."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        url = f"{TMDB_BASE_URL}/genre/movie/list"
        params = {"api_key": TMDB_API_KEY, "language": "tr-TR"}
        res = requests.get(url, params=params).json()

        genres = res.get("genres", [])
        for g in genres:
            cursor.execute(
                "UPDATE genres SET name_tr = %s WHERE id = %s",
                (g["name"], g["id"])
            )
        conn.commit()
        print(f"Saved Turkish names for {len(genres)} genres.")
    finally:
        cursor.close()
        conn.close()


def fetch_and_save_movie_translation(cursor, movie_id):
    """Fetches and saves the Turkish title/overview for ONE movie — but only
    if it doesn't already have one. That IS-NULL check happening right here
    (rather than only in the bulk WHERE clause below) is what makes this safe
    to call unconditionally for ANY movie, brand new or already long in the
    catalogue: an already-translated movie is just a fast no-op, no wasted
    TMDB request. That's what lets data/fetch_daily_popular_movies.py call
    this for every one of today's trending movies without first having to
    work out which of them are actually new — same pattern as
    fetch_and_save_credits()/fetch_and_save_keywords() in fetch_movies.py,
    which this function is deliberately written to sit alongside (same
    "takes an existing cursor, doesn't manage its own connection" shape).
    """
    cursor.execute("SELECT title_tr FROM movies WHERE id = %s", (movie_id,))
    row = cursor.fetchone()
    if row and row[0] is not None:
        return  # already translated — nothing to do

    try:
        url = f"{TMDB_BASE_URL}/movie/{movie_id}"
        params = {"api_key": TMDB_API_KEY, "language": "tr-TR"}
        res = requests.get(url, params=params)

        if res.status_code != 200:
            print(f"Could not fetch Turkish data for movie {movie_id} (status code: {res.status_code})")
            return

        data = res.json()
        # TMDB returns the ENGLISH title/overview back as a fallback if it has
        # no Turkish translation for this specific movie — storing that would
        # defeat the whole point (title_tr would just silently duplicate
        # title, and the language toggle would look broken for that movie
        # without ever knowing why). Only save it if TMDB actually gave us
        # something back AND that something isn't just an empty string.
        title_tr = data.get("title") or None
        overview_tr = data.get("overview") or None

        cursor.execute(
            "UPDATE movies SET title_tr = %s, overview_tr = %s WHERE id = %s",
            (title_tr, overview_tr, movie_id)
        )
        time.sleep(0.4)  # same rate-limit courtesy pause as fetch_movies.py

    except Exception as e:
        print(f"Unexpected error translating movie {movie_id}: {e}")


def fetch_and_save_movie_translations():
    """Bulk catch-up: Turkish title + overview for every movie in the
    catalogue that doesn't have one yet, in one run.

    Deliberately does NOT re-walk TMDB's "popular movies" pages the way
    data/fetch_movies.py does — that list changes over time (today's page 3
    might be tomorrow's page 5, or drop off the list entirely), so re-paging
    through it would risk mismatching movies. Going by our OWN existing movie
    IDs instead guarantees we ask TMDB for a translation of the exact same
    movie we already have, one request per movie via TMDB's single-movie
    endpoint (?language=tr-TR), rather than one request per PAGE of 20.
    """
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM movies WHERE title_tr IS NULL")
        movie_ids = [row[0] for row in cursor.fetchall()]
        print(f"{len(movie_ids)} movies still need a Turkish translation.")

        translated = 0
        for movie_id in movie_ids:
            fetch_and_save_movie_translation(cursor, movie_id)
            translated += 1
            if translated % 50 == 0:
                conn.commit()  # commit periodically, not just at the very end, so a crash partway through doesn't lose all the progress made so far
                print(f"  ...{translated}/{len(movie_ids)} done")

        conn.commit()
        print(f"Done — translated {translated} movies.")
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    print("Fetching Turkish genre names...")
    fetch_and_save_genre_translations()

    print("Fetching Turkish movie titles/overviews...")
    fetch_and_save_movie_translations()

    print("Translation import complete!")
