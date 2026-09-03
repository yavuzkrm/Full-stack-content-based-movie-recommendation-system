import mysql.connector          # lets Python talk to our MySQL database
import pandas as pd             # data-science library — turns SQL rows into a table (DataFrame) we can slice, sort and compute on
import numpy as np              # used below to build a zero-filled fallback matrix when a signal (e.g. keywords) has no data yet
import heapq                    # used below to grab just the "top N" similarity scores efficiently, without sorting the whole list
from sklearn.feature_extraction.text import TfidfVectorizer  # turns text (a movie's genres/overview/cast/keywords) into a vector of numbers, weighted by how distinctive each word is
from sklearn.metrics.pairwise import cosine_similarity        # measures how similar two of those vectors are (0 = unrelated, 1 = identical)
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))  # so the "from config import ..." below can find config.py, which lives one folder up
from config import DB_CONFIG

# --- How similarity is calculated -------------------------------------------
# Instead of gluing genres + overview + director + cast into one block of text
# and running a single TF-IDF/cosine-similarity pass over it, we compute FOUR
# separate similarity matrices — one per "kind" of similarity — and blend them
# together with our own weights. That mirrors how IMDb describes its own
# "More Like This" feature (built from several separate signals: genres, cast,
# and more, combined together) rather than one blurred-together score:
#
#   1. TEXT     — TF-IDF + cosine similarity on the overview/plot text. Our
#                 closest stand-in for "does this movie feel like that one".
#   2. KEYWORDS — TF-IDF + cosine similarity on TMDB's keyword tags (e.g.
#                 "time travel", "unreliable narrator") — much more specific
#                 than a broad genre, closer to Letterboxd's theme-driven
#                 "similar films" than a plain genre match is.
#   3. GENRE    — TF-IDF + cosine similarity on genre tags.
#   4. PEOPLE   — TF-IDF + cosine similarity on director + cast names.
#
# All four end up as one NxN matrix each (row i, column j = "how similar are
# movie i and movie j"), so they can just be added together once each is
# scaled by its weight. Change how much any one signal matters by editing its
# constant below — nothing else in this file needs to change.
TEXT_WEIGHT = 0.45
KEYWORD_WEIGHT = 0.25
GENRE_WEIGHT = 0.20
PEOPLE_WEIGHT = 0.10
# These four should always add up to 1.0 — if you tune one, adjust the others to match.

# --- in-memory caches -------------------------------------------------------
# Building the recommendation model (pulling every movie from MySQL, then computing
# a similarity score between every pair of movies) is the single most expensive
# thing this app does. It's far too slow to redo on every request, so we compute
# it once and keep the result sitting in memory (these three variables) for as
# long as the server keeps running. See get_data_and_matrix() below for how
# that caching actually works, and main.py for where we "warm up" this cache
# right when the server starts (instead of making the first visitor wait for it).
_movies_cache = None      # the finished DataFrame (one row per movie, with all its computed columns)
_sim_matrix_cache = None  # the movie-to-movie similarity scores
_df_cache = None          # the raw-ish DataFrame from load_data(), cached separately so repeated calls to load_data() are instant


def load_data():
    """
    Pulls every movie (plus its genres, directors and cast) out of MySQL and
    combines them into a single pandas DataFrame — one row per movie, with all
    the extra columns (weighted_rating, display_rating, a combined "content"
    column for text similarity, etc.) already computed and ready to use.

    This is the "expensive" step: several SQL queries plus some math. That's
    exactly why the result gets cached in _df_cache — call this function as
    many times as you like, it only actually does the work once per server run.
    """
    global _df_cache
    if _df_cache is not None:
        return _df_cache

    try:
        conn = mysql.connector.connect(**DB_CONFIG)
    except mysql.connector.Error as e:
        print(f"Database connection error: {e}")
        raise Exception(f"Could not connect to the database: {str(e)}")

    # dictionary=True makes each row come back as {"column_name": value, ...}
    # instead of a plain tuple — much easier to read and to hand to pandas.
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT id, title, overview, vote_avg, vote_count, poster_path FROM movies")
    movies_df = pd.DataFrame(cursor.fetchall())

    # A movie can have several genres, so we can't just add a "genre" column —
    # instead we ask MySQL to squash all of a movie's genre names into one
    # comma-separated string per movie (GROUP_CONCAT), giving us one row per
    # movie that we can cleanly merge onto the main table below.
    cursor.execute("""
        SELECT mg.movie_id, GROUP_CONCAT(g.name SEPARATOR ',') AS genres
        FROM movie_genres mg JOIN genres g ON mg.genre_id = g.id
        GROUP BY mg.movie_id
    """)
    genres_df = pd.DataFrame(cursor.fetchall())

    cursor.execute("""
        SELECT md.movie_id, GROUP_CONCAT(p.name SEPARATOR ', ') AS directors
        FROM movie_directors md JOIN people p ON md.person_id = p.id
        GROUP BY md.movie_id
    """)
    directors_df = pd.DataFrame(cursor.fetchall())

    cursor.execute("""
        SELECT mc.movie_id, GROUP_CONCAT(p.name ORDER BY p.name SEPARATOR ', ') AS cast
        FROM movie_cast mc JOIN people p ON mc.person_id = p.id
        GROUP BY mc.movie_id
    """)
    cast_df = pd.DataFrame(cursor.fetchall())

    cursor.execute("""
        SELECT mt.movie_id, GROUP_CONCAT(t.name ORDER BY t.name SEPARATOR ', ') AS keywords
        FROM movie_keywords mt JOIN keywords t ON mt.keyword_id = t.id
        GROUP BY mt.movie_id
    """)
    keywords_df = pd.DataFrame(cursor.fetchall())

    cursor.close()
    conn.close()

    # All four queries used "movie_id" as the column name, but the main table
    # calls it "id" — rename them so pandas' merge() can match rows up correctly.
    movies_df.rename(columns={"movie_id": "id"}, inplace=True)
    genres_df.rename(columns={"movie_id": "id"}, inplace=True)
    directors_df.rename(columns={"movie_id": "id"}, inplace=True)
    cast_df.rename(columns={"movie_id": "id"}, inplace=True)
    keywords_df.rename(columns={"movie_id": "id"}, inplace=True)

    # LEFT JOIN behaviour (how="left"): keep every movie even if it has no
    # genres/directors/cast on record — we don't want a movie to silently
    # disappear from the whole app just because its crew data is incomplete.
    df = movies_df.merge(genres_df, on="id", how="left")
    if not directors_df.empty:
        df = df.merge(directors_df, on="id", how="left")
    else:
        df["directors"] = pd.Series(dtype="object")  # keep the column present even with zero director rows, so later code doesn't break
    if not cast_df.empty:
        df = df.merge(cast_df, on="id", how="left")
    else:
        df["cast"] = pd.Series(dtype="object")
    if not keywords_df.empty:
        df = df.merge(keywords_df, on="id", how="left")
    else:
        df["keywords"] = pd.Series(dtype="object")  # same reasoning as directors/cast above — if TMDB keywords haven't been fetched yet (or none exist), the column still needs to exist so the fillna() below and the TF-IDF step in build_similarity_matrix() don't crash with a KeyError

    # Movies with no genres/overview/etc. show up as NaN after the merge —
    # turn those into empty strings so the text-concatenation below doesn't
    # produce the literal text "nan" inside a movie's content.
    df["genres"] = df["genres"].fillna("")
    df["overview"] = df["overview"].fillna("")
    df["directors"] = df["directors"].fillna("")
    df["cast"] = df["cast"].fillna("")
    df["keywords"] = df["keywords"].fillna("")

    # weighted_rating (Bayesian-adjusted) is for RANKING/SORTING only.
    # display_rating (the movie's real average) is for SHOWING to the user.
    # Mixing the two up anywhere in the frontend was a genuine bug we fixed —
    # see main.py's df_to_json_safe/row_to_json_safe for the JSON side of it.
    try:
        df = calculate_weighted_rating(df)
    except Exception as e:
        print(f"Weighted rating calculation error: {e}")
        df["weighted_rating"] = df["vote_avg"]  # fall back to the plain average if the math above ever fails

    df["display_rating"] = df["vote_avg"].round(1)

    _df_cache = df
    return df


def calculate_weighted_rating(df):
    """
    Computes IMDb-style "weighted rating" (a.k.a. the Bayesian average) for
    every movie, so that a movie with 5 votes averaging 9.9 doesn't outrank a
    movie with 50,000 votes averaging 8.5 — a handful of votes just isn't
    statistically reliable, so we pull small-sample scores back towards the
    overall average until they've earned enough votes to stand on their own.

        weighted_rating = (v / (v + m)) * R  +  (m / (v + m)) * C

    where:
        R = the movie's own average rating (vote_avg)
        v = the movie's own vote count
        C = the average rating across ALL movies (with at least one vote)
        m = the minimum vote count needed to be taken "seriously" — we set
            this to the 75th percentile of vote counts, i.e. a movie needs
            to be more-voted-on than 75% of the catalogue before its own
            score starts to matter more than the overall average.
    """
    df = df.copy()  # never mutate the caller's DataFrame in place
    df["vote_count"] = pd.to_numeric(df["vote_count"], errors="coerce").fillna(0)
    df["vote_avg"] = pd.to_numeric(df["vote_avg"], errors="coerce").fillna(0)

    valid = df[df["vote_count"] > 0]  # ignore movies with zero votes when computing the "overall average"
    C = valid["vote_avg"].mean() if not valid.empty else df["vote_avg"].mean()
    m = valid["vote_count"].quantile(0.75) if not valid.empty else 0

    v = df["vote_count"]
    R = df["vote_avg"]

    df["weighted_rating"] = (v / (v + m) * R) + (m / (v + m) * C)
    df["weighted_rating"] = df["weighted_rating"].round(1)
    df["display_rating"] = df["vote_avg"].round(1)

    return df


def _safe_tfidf_similarity(texts, stop_words=None):
    """
    Runs TfidfVectorizer + cosine_similarity on a column of text, but never
    crashes if that column turns out to be empty for every single movie (e.g.
    the `keywords` column, right after adding the keywords feature but before
    ever running the fetch script that actually populates it — every row is
    still just an empty string at that point). scikit-learn raises a
    ValueError ("empty vocabulary") in that situation; we catch it and hand
    back a matrix of all zeros instead, so that signal simply contributes
    nothing to the final blend until there's real data to work with, rather
    than taking the whole recommendation engine down.
    """
    try:
        matrix = TfidfVectorizer(stop_words=stop_words).fit_transform(texts)
        return cosine_similarity(matrix)
    except ValueError:
        n = len(texts)
        return np.zeros((n, n), dtype="float32")


def build_similarity_matrix(df):
    """
    Computes the four similarity signals described in the module-level
    comment above (text, keywords, genre, people) and blends them into one
    NxN matrix using TEXT_WEIGHT / KEYWORD_WEIGHT / GENRE_WEIGHT /
    PEOPLE_WEIGHT. Everything downstream of this function (recommend(),
    recommend_multi(), the pool/re-rank logic) only ever sees the single
    blended matrix it returns — none of that code needs to know or care that
    it's actually four signals combined.

    Note the `sim_matrix = ...; sim_matrix += ...` style below rather than
    computing all four matrices first and adding them in one expression: each
    NxN matrix takes real memory (it grows with the square of how many movies
    you have), so folding each one in immediately, one at a time, means only
    one "extra" matrix ever has to exist in memory at once instead of four.
    """
    sim_matrix = TEXT_WEIGHT * _safe_tfidf_similarity(df["overview"], stop_words="english")
    sim_matrix += KEYWORD_WEIGHT * _safe_tfidf_similarity(df["keywords"])
    sim_matrix += GENRE_WEIGHT * _safe_tfidf_similarity(df["genres"])
    sim_matrix += PEOPLE_WEIGHT * _safe_tfidf_similarity(df["directors"] + " " + df["cast"])
    return sim_matrix


def get_data_and_matrix():
    """
    The main entry point everything else in this file should call. Returns
    (dataframe, similarity_matrix), computing them the first time and just
    handing back the cached copies on every call after that.
    """
    global _movies_cache, _sim_matrix_cache
    if _movies_cache is not None and _sim_matrix_cache is not None:
        return _movies_cache, _sim_matrix_cache
    df = load_data()
    sim_matrix = build_similarity_matrix(df)
    _movies_cache = df
    _sim_matrix_cache = sim_matrix
    return df, sim_matrix


def _top_similarity_pool(sim_row, exclude_idx, pool_size):
    """
    Shared helper used by both recommend() and recommend_multi() below.
    Given one row of the similarity matrix (i.e. "how similar is every movie
    to the one(s) we searched for"), returns the `pool_size` most similar
    movies as a list of (index, score) pairs — excluding the searched movie(s)
    themselves.

    We use heapq.nlargest instead of sorting the entire list, because we only
    ever need the top handful (usually 50) out of what could be thousands of
    movies — nlargest does that in O(n log k) instead of O(n log n), which
    matters once the catalogue grows.
    """
    candidates = ((i, s) for i, s in enumerate(sim_row) if i not in exclude_idx)
    return heapq.nlargest(pool_size, candidates, key=lambda pair: pair[1])


def _hybrid_rerank(df, candidate_scores, top_n):
    """
    Shared second stage for both recommend() and recommend_multi(): takes a
    pool of "similar enough" candidates and re-sorts them using a hybrid score
    of 70% similarity + 30% quality (weighted_rating). "Similarity" here is
    already the blended text+keywords+genre+people score computed in
    build_similarity_matrix() — this function doesn't distinguish between
    those four, it just takes whatever single similarity number it's handed
    and balances it against quality.

    Why two stages instead of just blending sim + rating across the ENTIRE
    catalogue in one go? Because weighted_rating, once squeezed into a 0–1
    range, ends up spanning almost the whole range (a handful of blockbusters
    near 1, everything else near 0) — far wider than typical similarity
    scores. Blend that in globally and a handful of universally high-rated
    but completely unrelated movies would out-score genuinely similar ones on
    every single search, which is exactly the "it always recommends the same
    movies" bug we ran into and fixed. Narrowing to a similarity-based pool
    FIRST, and only using quality to break ties WITHIN that pool, keeps
    quality as a tie-breaker rather than letting it override relevance.
    """
    candidate_indices = [i for i, _ in candidate_scores]
    pool_wr = df.iloc[candidate_indices]["weighted_rating"]
    max_wr, min_wr = pool_wr.max(), pool_wr.min()
    wr_range = (max_wr - min_wr) or 1e-9  # avoid a divide-by-zero if every candidate has the same rating

    hybrid_scores = [
        (i, 0.7 * sim + 0.3 * ((df.iloc[i]["weighted_rating"] - min_wr) / wr_range))
        for i, sim in candidate_scores
    ]
    hybrid_scores.sort(key=lambda pair: pair[1], reverse=True)
    return [i for i, _ in hybrid_scores[:top_n]]


RESULT_COLUMNS = ["id", "title", "genres", "weighted_rating", "display_rating",
                  "overview", "poster_path", "directors", "cast"]


def recommend(movie_title: str, top_n: int = 10):
    """
    Given one movie title, returns the top_n most similar movies (see the
    module docstring above for how "similar" is actually calculated).
    Returns an empty DataFrame if the title isn't found in our catalogue.
    """
    df, sim_matrix = get_data_and_matrix()

    matches = df[df["title"].str.lower() == movie_title.lower()]
    if matches.empty:
        print(f"'{movie_title}' was not found in the catalogue.")
        return pd.DataFrame()

    idx = matches.index[0]
    pool_size = max(top_n * 5, 50)
    candidate_scores = _top_similarity_pool(sim_matrix[idx], {idx}, pool_size)
    top_indices = _hybrid_rerank(df, candidate_scores, top_n)

    result = df.iloc[top_indices][RESULT_COLUMNS].reset_index(drop=True)
    result.index += 1  # start numbering results at 1 instead of 0, purely so it reads naturally ("recommendation #1") if ever printed
    return result


def recommend_multi(movie_titles: list[str], top_n: int = 10):
    """
    Same idea as recommend(), but for 2–5 movies at once: we average the
    similarity of every candidate movie against ALL of the input movies, so
    the result reflects the whole group's taste rather than just one title.
    """
    df, sim_matrix = get_data_and_matrix()

    input_indices = []
    for title in movie_titles:
        matches = df[df["title"].str.lower() == title.lower()]
        if not matches.empty:
            input_indices.append(matches.index[0])
        else:
            print(f"'{title}' was not found in the catalogue.")

    if len(input_indices) < 2:
        print("Not enough of the given movies were found to build a recommendation.")
        return pd.DataFrame()

    avg_sim_row = sim_matrix[input_indices].mean(axis=0)  # one similarity score per movie, averaged across all the input movies
    pool_size = max(top_n * 5, 50)
    candidate_scores = _top_similarity_pool(avg_sim_row, set(input_indices), pool_size)
    top_indices = _hybrid_rerank(df, candidate_scores, top_n)

    result = df.iloc[top_indices][RESULT_COLUMNS].reset_index(drop=True)
    result.index += 1
    return result
