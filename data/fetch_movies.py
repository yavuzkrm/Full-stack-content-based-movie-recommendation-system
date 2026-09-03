import requests  # for making HTTP calls out to the TMDB API
import mysql.connector
import time      # only used for time.sleep() — pausing between API calls so we don't get rate-limited
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from config import TMDB_API_KEY, TMDB_BASE_URL, DB_CONFIG

# This script is meant to be run BY HAND, once in a while (e.g. `python -m data.fetch_movies`
# from the project root), to populate or refresh the movie catalogue. It's separate
# from the Flask app itself — the app only ever READS from the database, it never
# calls TMDB directly for the main catalogue (only main.py's daily "trending" refresh does).


def get_db():
    return mysql.connector.connect(**DB_CONFIG)


def fetch_and_save_genres(cursor):
    """Pulls TMDB's fixed list of genres (Action, Comedy, Drama, ...) and saves
    them to our `genres` table.

    Note the language parameter: it's set to en-US. This matters more than it
    looks — the genre NAME is what actually shows up as a tag on every movie
    card in the app, so if this were fetched in a different language, every
    genre chip in an otherwise-English app would suddenly be in that language
    too. We use "INSERT ... ON DUPLICATE KEY UPDATE" rather than "INSERT
    IGNORE" here on purpose: IGNORE would silently keep whatever name was
    already stored the first time this ever ran, so if you ever change the
    language (or TMDB renames a genre), re-running this function is what
    actually refreshes the names already in the database."""
    url = f"{TMDB_BASE_URL}/genre/movie/list"
    params = {"api_key": TMDB_API_KEY, "language": "en-US"}
    res = requests.get(url, params=params).json()
    # `res` looks like: {"genres": [{"id": 28, "name": "Action"}, ...]}

    genres = res.get("genres", [])  # .get() with a default means this can't crash even if TMDB's response is ever missing the "genres" key
    for g in genres:
        cursor.execute(
            "INSERT INTO genres (id, name) VALUES (%s, %s) "
            "ON DUPLICATE KEY UPDATE name = VALUES(name)",
            (g["id"], g["name"]),
        )
    print(f"Saved {len(genres)} genres.")


def fetch_and_save_credits(cursor, movie_id):
    """Fetches the director(s) and top cast members for one movie and saves
    them. Directors and cast members both live in the shared `people` table
    (see schema.sql for why), linked to the movie through movie_directors /
    movie_cast."""
    try:
        url = f"{TMDB_BASE_URL}/movie/{movie_id}/credits"
        params = {"api_key": TMDB_API_KEY}
        res = requests.get(url, params=params)

        if res.status_code != 200:
            print(f"Could not fetch credits for movie {movie_id} (status code: {res.status_code})")
            return

        data = res.json()

        main_cast = data.get("cast", [])[:10]  # only keep the top-billed 10 actors — the full cast list can be 50+ people long and we don't need all of them for recommendations or display
        directors = [member for member in data.get("crew", []) if member.get("job") == "Director"]

        for director in directors:
            person_id = director["id"]
            cursor.execute(
                "INSERT IGNORE INTO people (id, name) VALUES (%s, %s)",
                (person_id, director["name"])
            )
            cursor.execute(
                "INSERT IGNORE INTO movie_directors (movie_id, person_id) VALUES (%s, %s)",
                (movie_id, person_id)
            )

        for actor in main_cast:
            person_id = actor["id"]
            cursor.execute(
                "INSERT IGNORE INTO people (id, name) VALUES (%s, %s)",
                (person_id, actor["name"])
            )
            cursor.execute(
                "INSERT IGNORE INTO movie_cast (movie_id, person_id, character_name) VALUES (%s, %s, %s)",
                (movie_id, person_id, actor.get("character"))
            )

        time.sleep(0.4)  # a short pause between requests so we don't hammer TMDB's API and get rate-limited

    except Exception as e:
        print(f"Unexpected error while fetching credits for movie {movie_id}: {e}")

def fetch_and_save_keywords(cursor, movie_id):

    try:
        url = f"{TMDB_BASE_URL}/movie/{movie_id}/keywords"
        params = {"api_key": TMDB_API_KEY}
        res = requests.get(url, params=params)
    
        if res.status_code != 200:
            print(f"Could not fetch keywords for movie {movie_id} (status code: {res.status_code})")
            return
    
        data = res.json()
        keywords = data.get("keywords", [])

        for keyword in keywords:
            keyword_id = keyword["id"]
            cursor.execute(
                "INSERT IGNORE INTO keywords (id, name) VALUES (%s, %s)",
                (keyword_id, keyword["name"])
            )
            cursor.execute(
                "INSERT IGNORE INTO movie_keywords (movie_id, keyword_id) VALUES (%s, %s)",
                (movie_id, keyword_id)
            )

        time.sleep(0.4) 
    
    except Exception as e:
        print(f"Unexpected error while fetching keywords for movie {movie_id}: {e}")

    
def fetch_and_save_movies(conn, cursor, total_pages=10):
    """Pulls TMDB's "popular movies" list, `total_pages` pages of 20 movies
    each, and saves everything (movie details, genres, director, cast) to the
    database. This is the slow, one-time (or occasional) bulk-import step —
    expect it to take a while, since we deliberately pause between requests
    to stay within TMDB's rate limits."""
    saved = 0

    for page in range(1, total_pages + 1):
        url = f"{TMDB_BASE_URL}/movie/popular"
        params = {"api_key": TMDB_API_KEY, "language": "en-US", "page": page}
        movies = requests.get(url, params=params).json().get("results", [])

        for m in movies:
            movie_id = m["id"]

            cursor.execute(
                """
                INSERT IGNORE INTO movies
                    (id, title, overview, release_date, vote_avg, vote_count, poster_path)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    m["id"],
                    m.get("title"),
                    m.get("overview"),
                    m.get("release_date") or None,  # store NULL instead of an empty string if TMDB didn't give us a release date
                    m.get("vote_average"),
                    m.get("vote_count"),
                    m.get("poster_path"),
                ),
            )

            for genre_id in m.get("genre_ids", []):
                cursor.execute(
                    "INSERT IGNORE INTO movie_genres (movie_id, genre_id) VALUES (%s, %s)",
                    (m["id"], genre_id),
                )

            fetch_and_save_credits(cursor, movie_id)
            fetch_and_save_keywords(cursor, movie_id)
            saved += 1

        print(f"  Page {page}/{total_pages} done ({saved} movies so far).")
        conn.commit()  # everything above runs inside one transaction per page — commit() is what actually writes it to disk; without it, all these INSERTs would just evaporate if the script crashed partway through
        time.sleep(1.5)  # a longer pause between pages, on top of the per-movie pause in fetch_and_save_credits, to stay well under TMDB's rate limit

    print(f"Done — saved {saved} movies in total.")


if __name__ == "__main__":
    conn = get_db()
    cursor = conn.cursor()

    print("Fetching genres...")
    fetch_and_save_genres(cursor)
    conn.commit()

    print("Fetching movies...")
    fetch_and_save_movies(conn, cursor, total_pages=500)

    cursor.close()
    conn.close()
    print("Import complete!")
