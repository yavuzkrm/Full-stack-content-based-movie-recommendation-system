<p align="center">
  <img src="static/images/logo.png" alt="NextWatch" width="420">
</p>

<p align="center">
  <b>A full-stack, content-based movie recommendation engine</b> — built with Flask, MySQL,
  and a hand-tuned hybrid similarity model. No third-party recommendation API,
  no black box: every suggestion is computed from scratch out of TMDB data.
</p>

<p align="center">
  <a href="https://film-recommendation-system-production-29d8.up.railway.app/"><b>🎬 Live demo</b></a>
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white">
  <img alt="Flask" src="https://img.shields.io/badge/Flask-2.x-000000?logo=flask&logoColor=white">
  <img alt="MySQL" src="https://img.shields.io/badge/MySQL-8.0-4479A1?logo=mysql&logoColor=white">
  <img alt="scikit-learn" src="https://img.shields.io/badge/scikit--learn-TF--IDF-F7931E?logo=scikitlearn&logoColor=white">
  <img alt="Deployed on Railway" src="https://img.shields.io/badge/Deployed%20on-Railway-0B0D0E?logo=railway&logoColor=white">
</p>

---

Search for a movie you like — or a handful of them at once — and NextWatch
hands back a ranked list of similar titles, complete with genres, cast,
director and posters pulled live from [TMDB](https://www.themoviedb.org/).
Under the hood it's not one fuzzy text match: it's four independent
similarity signals (plot, keywords, genre, cast/director), each computed
with TF-IDF + cosine similarity and blended with hand-tuned weights, then
re-ranked by a Bayesian "quality" score so a handful of 10/10 votes can't
outrank a movie 50,000 people actually watched and loved.

## ✨ Features

- 🎯 **Single or multi-movie recommendations** — search one title, or pick
  2–5 movies to blend into a single set of suggestions that reflects the
  whole group's taste.
- 🔎 **Search-as-you-type**, ranked so titles that *start with* your query
  surface before ones that just happen to contain it somewhere in the middle.
- 👤 **Accounts** — favourites (max 5), a watchlist, a "watched" list, and
  1–10 star ratings, all editable straight from any movie card.
- 🔥 **Trending Today** — a row that refreshes automatically every day,
  straight from TMDB's own trending chart.
- 🧠 **A four-signal hybrid recommendation model** built from scratch — see
  below for exactly how it works, not just that it does.
- 🔐 Hardened for production: rate-limited auth endpoints, secure session
  cookies, password rules enforced on both frontend and backend.

## 🧠 How recommendations actually work

Instead of gluing genres, overview, cast and director into one block of text
and running a single similarity pass over it, the engine computes **four
separate** similarity signals and blends them together with its own weights
(tunable via `TEXT_WEIGHT` / `KEYWORD_WEIGHT` / `GENRE_WEIGHT` /
`PEOPLE_WEIGHT` at the top of `recommend/engine.py`):

| Signal | What it compares | Why it's separate |
|---|---|---|
| **Text** (45%) | TF-IDF + cosine similarity on the plot/overview | Closest stand-in for "does this movie *feel* like that one" |
| **Keywords** (25%) | TMDB's keyword tags (e.g. "time travel", "unreliable narrator") | Much more specific than genre — closer to Letterboxd's theme-driven "similar films" |
| **Genre** (20%) | Genre tags | The broad-strokes category signal |
| **People** (10%) | Director + cast names | Rewards "more from the same director/actor" |

Each signal produces its own N×N similarity matrix; they're summed by weight
into a single blended score. A shortlist of the most similar movies is built
from that blended score first, and **only then** re-ranked by a Bayesian
"weighted rating" (an IMDb-style adjustment) — as a tie-breaker *within* that
shortlist, never as a way to let an unrelated-but-popular movie crowd out a
genuinely similar one. That two-stage design is what stops the classic "it
just keeps recommending the same ten blockbusters" failure mode.

## 🛠 Tech stack

| Layer          | What's used |
|----------------|-------------|
| Backend        | Python, Flask, gunicorn |
| Database       | MySQL |
| Recommendation | pandas, scikit-learn (TF-IDF + cosine similarity) |
| Frontend       | Plain HTML/CSS/JavaScript — no framework, no build step |
| Data source    | [TMDB API](https://www.themoviedb.org/documentation/api) |
| Deployment     | Railway (web service + a second always-on service for the daily refresh job) |

## 📂 Project structure

```
.
├── main.py                         # Flask app — all /api/... routes live here
├── refresh_daily_popular_movies.py # standalone process that keeps "Trending Today" fresh (see Deployment)
├── config.py                       # loads .env, sets up the DB connection pool
├── requirements.txt
├── db/
│   └── schema.sql                  # run this once to create the database & tables
├── data/
│   ├── fetch_movies.py             # one-time/occasional bulk import from TMDB
│   └── fetch_daily_popular_movies.py  # TMDB fetch/DB logic used by the daily refresh
├── recommend/
│   └── engine.py                   # the recommendation model itself
├── user/
│   └── auth.py                     # accounts, favourites, watchlist, watched, ratings
├── static/images/                  # logo + favicons
└── templates/index.html            # the entire frontend (HTML + CSS + JS in one file)
```

---

## 🚀 Running it locally

**Prerequisites:** Python 3.10+, a local MySQL 8.0+ server, and a free
[TMDB API key](https://www.themoviedb.org/settings/api) (sign up, then
generate a key — any hobby-project description works).

```bash
# 1. Clone and install
git clone https://github.com/yavuzkrm/Full-stack-content-based-movie-recommendation-system
cd Full-stack-content-based-movie-recommendation-system
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. Configure
cp .env.example .env   # then open .env and fill in TMDB_API_KEY, your MySQL
                        # credentials, and a random SECRET_KEY (generate one with:
                        # python3 -c "import secrets; print(secrets.token_hex(32))")

# 3. Create the database (make sure MySQL is running first)
mysql -u root -p < db/schema.sql

# 4. Import the movie catalogue from TMDB (takes a while — TMDB rate-limits this)
python -m data.fetch_movies

# 5. Run the app
gunicorn main:app --reload
```

Open **http://localhost:8000**. The first request warms up the
recommendation engine (builds the similarity model), which is normal and
only happens once per process start.

> Leave `APP_ENV=development` in your local `.env` — it's what tells the app
> it's fine to send the login cookie over plain `http://localhost` instead of
> requiring HTTPS. Don't set it in production; see [Deployment](#-deployment) below.

<details>
<summary><b>Troubleshooting</b> (click to expand)</summary>

- **`mysql: command not found`** — MySQL's CLI isn't on your PATH; use its
  full path (e.g. `/usr/local/mysql/bin/mysql` on macOS) or add it to PATH.
- **`Access denied for user 'root'@'localhost'`** — `MYSQLPASSWORD` in `.env`
  doesn't match your actual MySQL root password.
- **`gunicorn: command not found`** — your virtual environment isn't
  activated, or `pip install -r requirements.txt` failed partway — check its
  output for errors.
- **Search/recommend endpoints return nothing** — step 4 hasn't finished.
  Check row counts: `mysql -u root -p -e "SELECT COUNT(*) FROM film_oneri.movies;"`.
- **`Could not connect to the database` on startup** — MySQL isn't running;
  start it (`mysql.server start` on macOS, `sudo systemctl start mysql` on Linux).
- **You get logged out immediately after logging in** — set
  `APP_ENV=development` in `.env` (see the note above the login cookie is
  otherwise marked HTTPS-only).

</details>

## ☁️ Deployment

In production, drop `--reload`:

```bash
gunicorn main:app
```

Don't set `APP_ENV` in production (or set it to `production`) so the login
cookie requires HTTPS, and make sure `SECRET_KEY` is a real random value —
never the placeholder from `.env.example`.

Gunicorn can run several worker processes, each importing `main.py`
separately — so a scheduler started *inside* `main.py` would fire once per
worker instead of once a day. That's why the daily "Trending Today" refresh
lives in its own standalone script, deployed as a **second, always-on
service** alongside the web app (e.g. a second service in the same Railway
project):

```bash
python refresh_daily_popular_movies.py
```

It refreshes the list once immediately on startup and then every 24 hours —
so "Trending Today" is never left empty right after a deploy. It's **not** a
fit for a "Cron Job"-style service, since those expect the command to exit,
not run forever. Worth an occasional check in Railway's dashboard that both
services are still up — if the refresh service dies, the site keeps working
fine, it just stops updating "Trending Today", with no visible error.

## 📝 Notes

- The recommendation model, the search index, and the "Trending Today" cache
  all live in memory and rebuild automatically on server restart — nothing
  to sync by hand.
- Missing data doesn't crash the engine — a signal with no data (e.g.
  keywords not fetched yet for an older movie) just contributes nothing to
  the blend until real data is there.
- `/api/login` and `/api/register` are rate-limited per IP (10/min and
  10/hour respectively) against brute-forcing and mass account creation. If
  you ever scale this to multiple workers/instances, point flask-limiter's
  `storage_uri` at Redis instead of its default in-memory store.
