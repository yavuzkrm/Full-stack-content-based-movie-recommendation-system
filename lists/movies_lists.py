from recommend.engine import get_data_and_matrix, RESULT_COLUMNS
from config import cnxpool

# Reuses engine.py's RESULT_COLUMNS as-is (same shape as a search-result card:
# overview/genres/cast inline, not just a bare poster) instead of redefining
# an identical list here — these lists show a full recCard-style card, so
# unlike a plain poster grid they genuinely need the detail fields.
LIST_COLUMNS = RESULT_COLUMNS


def get_all_genres():
    """Every genre's English + Turkish name, sorted alphabetically — lets the
    frontend render a "browse by genre" row without hardcoding the genre list
    itself (which would silently drift out of sync with whatever's actually
    in the database). A tiny, separate DB query rather than something pulled
    from the big cached DataFrame in engine.py, since the `genres` table only
    ever has a couple dozen rows — no real cost to just asking MySQL directly
    each time, and it keeps this one query independent of the recommendation
    engine's cache lifecycle."""
    conn = cnxpool.get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT name, COALESCE(name_tr, name) AS name_tr FROM genres ORDER BY name")
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()



def top_250():
    """The 250 highest weighted_rating movies in the whole catalogue.

    Returns a raw DataFrame slice (not .to_dict()'d) on purpose — main.py's
    /api/top250 route runs this through df_to_json_safe() before it becomes
    JSON, which is also what converts any NaN ratings into valid JSON `null`
    (see main.py's df_to_json_safe docstring for why that matters). Calling
    .to_dict() in here instead would both skip that safety step AND hand
    main.py a plain list where it expects a DataFrame — df_to_json_safe()
    calls .astype()/.where() on its input, which only a DataFrame has.
    """
    df, _ = get_data_and_matrix()
    # A secondary sort key (movie id) matters here, not just for tidiness — MySQL makes no
    # promise about what order rows come back in when a query has no ORDER BY (see the
    # `movies` SELECT in engine.py's load_data()), and weighted_rating is rounded to 1
    # decimal place, so plenty of movies genuinely tie on it. Without a tie-breaker, those
    # tied movies' relative order depends on whatever incidental order MySQL happened to
    # return them in THIS TIME — which can (and does) shift after a restart/redeploy, making
    # the Top 250 order look like it's randomly reshuffling itself for no reason. Sorting by
    # id as well guarantees the exact same final order every time, regardless of row order.
    top_250_movies = df.sort_values(by=["weighted_rating", "id"], ascending=[False, True]).head(250)
    top_250_movies["bucket"] = top_250_movies["weighted_rating"].round(1)
    top_250_movies.sort_values(["bucket", "display_rating", "id"], ascending=[False, False, True])
    return top_250_movies[LIST_COLUMNS]


def movies_by_genre(genre_name, top_n=30):
    """The top_n highest-rated movies in a single genre (e.g. "Action").

    Same DataFrame-not-dict return convention as top_250() above, for the
    same reason — main.py wraps this in df_to_json_safe() too.
    """
    df, _ = get_data_and_matrix()
    # A plain df["genres"].str.contains(genre_name) would also match a genre
    # name that merely appears as a SUBSTRING of another one — comparing
    # against the exact, comma-split list of tags avoids that false-positive.
    mask = df["genres"].apply(lambda g: genre_name in [x.strip() for x in g.split(",")])
    genre_movies = df[mask]
    # Same tie-breaker reasoning as top_250() above — without it, this list's order could
    # shift after every restart purely because of MySQL's unordered row delivery, not
    # because anything about the movies themselves actually changed.
    top_genre_movies = genre_movies.sort_values(by=["weighted_rating", "id"], ascending=[False, True]).head(top_n)
    top_genre_movies["bucket"] = top_genre_movies["weighted_rating"].round(1)
    top_genre_movies.sort_values(["bucket", "display_rating", "id"], ascending=[False, False, True])
    return top_genre_movies[LIST_COLUMNS]
