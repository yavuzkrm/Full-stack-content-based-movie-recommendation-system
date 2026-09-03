-- ================================================
-- Movie Recommendation System — MySQL schema
-- ================================================
-- Run this once against a fresh MySQL server to create the database and every
-- table the app needs. After that, `data/fetch_movies.py` fills the movie/genre/
-- people tables from TMDB, and the Flask app (main.py) reads and writes the rest
-- as people use the site.

CREATE DATABASE IF NOT EXISTS film_oneri CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE film_oneri;

-- One row per movie. `id` is TMDB's own movie ID (not auto-generated here), so
-- our data always lines up with TMDB's if we ever need to re-fetch something.
CREATE TABLE IF NOT EXISTS movies (
    id          INT PRIMARY KEY,          -- TMDB movie ID
    title       VARCHAR(300) NOT NULL,
    overview    TEXT,
    release_date DATE,
    vote_avg    FLOAT,
    vote_count  INT,
    poster_path VARCHAR(200),
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- The fixed list of genres TMDB uses (Action, Comedy, Drama, ...).
CREATE TABLE IF NOT EXISTS genres (
    id   INT PRIMARY KEY,
    name VARCHAR(100) NOT NULL
);

-- A movie can have several genres, and a genre obviously covers many movies —
-- that's a many-to-many relationship, which in SQL always needs its own link
-- table like this one instead of a column on `movies`.
-- The PRIMARY KEY (movie_id, genre_id) does double duty: it stops the same
-- movie/genre pair being inserted twice, AND — because MySQL automatically
-- indexes the leftmost column(s) of any key — it makes "give me all genres
-- for movie X" (WHERE movie_id = X) fast without needing a separate index.
CREATE TABLE IF NOT EXISTS movie_genres (
    movie_id INT,
    genre_id INT,
    PRIMARY KEY (movie_id, genre_id),
    FOREIGN KEY (movie_id) REFERENCES movies(id) ON DELETE CASCADE,
    FOREIGN KEY (genre_id) REFERENCES genres(id) ON DELETE CASCADE
);

-- Registered users. Passwords are never stored in plain text — only a salted
-- hash (see werkzeug's generate_password_hash in user/auth.py) ever touches
-- this table.
CREATE TABLE IF NOT EXISTS users (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    username   VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- One row per (user, movie) rating. A user can only rate a given movie once —
-- rating it again just updates this row (see the "ON DUPLICATE KEY UPDATE" in
-- user/auth.py's save_rating()) instead of creating a duplicate.
CREATE TABLE IF NOT EXISTS user_ratings (
    user_id    INT,
    movie_id   INT,
    rating     FLOAT NOT NULL CHECK (rating BETWEEN 1 AND 10),
    rated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, movie_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (movie_id) REFERENCES movies(id) ON DELETE CASCADE
);

-- Movies a user has marked as watched.
CREATE TABLE IF NOT EXISTS user_watched (
    user_id   INT,
    movie_id  INT,
    added_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, movie_id),
    FOREIGN KEY (user_id)  REFERENCES users(id)  ON DELETE CASCADE,
    FOREIGN KEY (movie_id) REFERENCES movies(id) ON DELETE CASCADE
);

-- A user's "watch later" list.
CREATE TABLE IF NOT EXISTS user_watchlist (
    user_id   INT,
    movie_id  INT,
    added_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, movie_id),
    FOREIGN KEY (user_id)  REFERENCES users(id)  ON DELETE CASCADE,
    FOREIGN KEY (movie_id) REFERENCES movies(id) ON DELETE CASCADE
);

-- A user's favourites (the app caps this at 5 — see FAVOURITES_LIMIT in main.py).
CREATE TABLE IF NOT EXISTS user_favourites (
    user_id   INT,
    movie_id  INT,
    added_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, movie_id),
    FOREIGN KEY (user_id)  REFERENCES users(id)  ON DELETE CASCADE,
    FOREIGN KEY (movie_id) REFERENCES movies(id) ON DELETE CASCADE
);

-- Shared table for both actors and directors — a "person" from TMDB. Keeping
-- them in one table (instead of a separate `actors` and `directors` table)
-- avoids duplicating a person who happens to do both across two movies.
CREATE TABLE IF NOT EXISTS people (
    id INT PRIMARY KEY, -- TMDB's person_id
    name VARCHAR(255) NOT NULL
);

-- Which actors appear in which movies (and as which character).
CREATE TABLE IF NOT EXISTS movie_cast (
    movie_id INT,
    person_id INT,
    character_name VARCHAR(255),
    PRIMARY KEY (movie_id, person_id), -- composite key: one row per (movie, actor) pair
    FOREIGN KEY (movie_id) REFERENCES movies(id) ON DELETE CASCADE,
    FOREIGN KEY (person_id) REFERENCES people(id) ON DELETE CASCADE
);

-- Which directors directed which movies.
CREATE TABLE IF NOT EXISTS movie_directors (
    movie_id INT,
    person_id INT,
    PRIMARY KEY (movie_id, person_id),
    FOREIGN KEY (movie_id) REFERENCES movies(id) ON DELETE CASCADE,
    FOREIGN KEY (person_id) REFERENCES people(id) ON DELETE CASCADE
);

-- Today's trending movies, refreshed once a day by the background scheduler in
-- main.py. `rank_id` auto-increments in insertion order, which is also TMDB's
-- trending order — that's why data/fetch_daily_popular_movies.py sorts by it
-- when reading this table back, so the homepage shows movies in the same order
-- TMDB ranked them.
CREATE TABLE popular_today (
    rank_id    INT AUTO_INCREMENT,
    movie_id   INT,
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(rank_id),
    FOREIGN KEY (movie_id) REFERENCES movies(id) ON DELETE CASCADE
);


CREATE TABLE keywords (
    id   INT PRIMARY KEY,
    name VARCHAR(150) NOT NULL
);

CREATE TABLE movie_keywords (
    movie_id INT,
    keyword_id INT,
    PRIMARY KEY (movie_id, keyword_id),
    FOREIGN KEY (movie_id) REFERENCES movies(id) ON DELETE CASCADE,
    FOREIGN KEY (keyword_id) REFERENCES keywords(id) ON DELETE CASCADE
);