import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from config import TMDB_API_KEY, TMDB_BASE_URL, cnxpool
from data.fetch_movies import fetch_and_save_credits, fetch_and_save_keywords
import requests
import mysql.connector


def get_db():
    # Reuses the same shared connection pool as the rest of the app (see
    # config.py) instead of opening a brand new MySQL connection from
    # scratch — this used to connect directly with mysql.connector.connect(),
    # which works fine but skips the pool's benefit of reusing already-open
    # connections.
    return cnxpool.get_connection()


def fetch_popular_movie():
    """Pulls today's top 10 trending movies from TMDB and saves them —
    both into the main `movies` table (in case one of them is completely new
    to our catalogue) and into `popular_today`, which is what the homepage's
    "Trending Today" row actually reads from."""
    conn = get_db()
    cursor = conn.cursor()

    url = f"{TMDB_BASE_URL}/trending/movie/day"
    params = {"api_key": TMDB_API_KEY, "language": "en-US"}
    res = requests.get(url, params=params)
    data = res.json().get("results", [])[:10]

    for m in data:
        # INSERT IGNORE: if this movie is already in our catalogue, this is a
        # no-op — we don't want to overwrite details we might already have.
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
                m.get("release_date") or None,
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

        fetch_and_save_credits(cursor, m["id"])
        fetch_and_save_keywords(cursor, m["id"])

        # popular_today has no unique constraint on movie_id (only rank_id is
        # a key), so this INSERT always adds a new row — that's intentional,
        # since truncate_popular_movie() below wipes the table clean once a
        # day right before this function refills it.
        cursor.execute("INSERT INTO popular_today (movie_id) VALUES (%s)", (m["id"],))

    conn.commit()
    cursor.close()
    conn.close()


def truncate_popular_movie():
    """Empties the "trending today" table so fetch_popular_movie() can fill
    it back up with a fresh list. Called once a day by the scheduled job in
    main.py, right before fetch_popular_movie()."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("TRUNCATE TABLE popular_today")
    conn.commit()
    cursor.close()
    conn.close()


def get_popular_movies():
    """Reads today's trending movies back out, with full details (genres,
    director, cast) joined in, ready for the frontend to render as cards.

    ORDER BY pt.rank_id preserves the order TMDB gave us in the first place
    (rank_id auto-increments in insertion order — see popular_today in
    schema.sql) — without it, MySQL is free to return the GROUP BY'd rows in
    whatever order it finds convenient, which could silently scramble the
    "Trending Today" row on the homepage every time the cache refreshes."""
    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT
                m.id, m.title, m.poster_path, m.overview, m.vote_avg,
                GROUP_CONCAT(DISTINCT g.name SEPARATOR ',') AS genres,
                GROUP_CONCAT(DISTINCT pd.name SEPARATOR ', ') AS directors,
                GROUP_CONCAT(DISTINCT pc.name SEPARATOR ', ') AS cast
            FROM popular_today pt
            LEFT JOIN movies m ON m.id = pt.movie_id
            LEFT JOIN movie_genres mg ON mg.movie_id = m.id
            LEFT JOIN genres g ON g.id = mg.genre_id
            LEFT JOIN movie_directors md ON md.movie_id = m.id
            LEFT JOIN people pd ON pd.id = md.person_id
            LEFT JOIN movie_cast mc ON mc.movie_id = m.id
            LEFT JOIN people pc ON pc.id = mc.person_id
            GROUP BY pt.rank_id, m.id, m.title, m.poster_path, m.overview, m.vote_avg
            ORDER BY pt.rank_id ASC
        """)
        return cursor.fetchall()
    except mysql.connector.Error as err:
        print(f"Error: {err}")
        return []
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    truncate_popular_movie()
    fetch_popular_movie()
    popular_movies = get_popular_movies()
    print(f"Fetched {len(popular_movies)} trending movies.")
