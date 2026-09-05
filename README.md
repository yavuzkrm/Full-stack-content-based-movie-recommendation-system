# NextWatch — Movie Recommendation Engine

A full-stack movie recommendation site built with Flask, MySQL, and a
content-based recommendation model. Search for a movie you like — or a
handful of them at once — and get back a ranked list of similar titles, with
genres, cast, director and posters pulled from [TMDB](https://www.themoviedb.org/).

## Features

- **Single or multi-movie recommendations** — search one title, or pick 2–5
  movies to blend into a single set of suggestions.
- **Search-as-you-type**, with results ranked so titles that *start with*
  your query show up before ones that just happen to contain it somewhere.
- **Accounts** with favourites (max 5), a watchlist, a "watched" list, and
  1–10 star ratings — all editable straight from any movie card or its detail
  view.
- **Trending Today** row, refreshed automatically once a day from TMDB.
- A four-signal hybrid recommendation model — see below.

## How recommendations work

Rather than gluing genres, overview, cast and director into one block of text
and running a single similarity comparison over it, the engine computes four
**separate** similarity signals and blends them together with its own
weights (see `TEXT_WEIGHT` / `KEYWORD_WEIGHT` / `GENRE_WEIGHT` /
`PEOPLE_WEIGHT` at the top of `recommend/engine.py`):

1. **Text** — TF-IDF + cosine similarity on the movie's overview/plot.
2. **Keywords** — TF-IDF + cosine similarity on TMDB's keyword tags (e.g.
   "time travel", "unreliable narrator") — much more specific than a broad
   genre, and the closest thing this project has to Letterboxd's
   review-mined "similar films" theming.
3. **Genre** — TF-IDF + cosine similarity on genre tags.
4. **People** — TF-IDF + cosine similarity on director + cast names.

Once a shortlist of the most similar movies is built this way, it's re-ranked
one more time by a Bayesian "weighted rating" (an IMDb-style adjustment that
keeps a movie with 5 near-perfect votes from outranking one with 50,000
slightly-lower votes) — but only as a tie-breaker *within* that already-
relevant shortlist, never as a way to let an unrelated but popular movie
crowd out a genuinely similar one.

## Tech stack

| Layer          | What's used |
|----------------|-------------|
| Backend        | Python, Flask, gunicorn |
| Database       | MySQL |
| Recommendation | pandas, scikit-learn (TF-IDF + cosine similarity) |
| Frontend       | Plain HTML/CSS/JavaScript — no framework, no build step |
| Data source    | [TMDB API](https://www.themoviedb.org/documentation/api) |

## Project structure

```
.
├── main.py                        # Flask app — all /api/... routes live here
├── refresh_daily_popular_movies.py # standalone process that keeps "Trending Today" fresh (see Deployment below)
├── config.py                      # loads .env, sets up the DB connection pool
├── requirements.txt
├── db/
│   └── schema.sql                 # run this once to create the database & tables
├── data/
│   ├── fetch_movies.py            # one-time/occasional bulk import from TMDB
│   └── fetch_daily_popular_movies.py  # the actual TMDB fetch/DB logic, called by refresh_daily_popular_movies.py
├── recommend/
│   └── engine.py                  # the actual recommendation model
├── user/
│   └── auth.py                    # accounts, favourites, watchlist, watched, ratings
├── static/
│   └── images/                    # logo + favicon, served automatically by Flask
└── templates/
    └── index.html                 # the entire frontend (HTML + CSS + JS in one file)
```

## Getting started

**1. Clone the repo and install dependencies**

```bash
git clone https://github.com/yavuzkrm/Full-stack-content-based-movie-recommendation-system
cd Full-stack-content-based-movie-recommendation-system
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

**2. Set up your environment variables**

```bash
cp .env.example .env
```

Then open `.env` and fill in a [TMDB API key](https://www.themoviedb.org/settings/api)
and your MySQL connection details.

**3. Create the database**

Make sure MySQL is running, then:

```bash
mysql -u root -p < db/schema.sql
```

**4. Import a movie catalogue from TMDB**

This fetches genres, keywords, and several thousand movies (with cast/director
info) and can take a while — TMDB rate limits mean the script deliberately
pauses between requests.

```bash
python -m data.fetch_movies
```

**5. Run the app**

run it through gunicorn:

```bash
gunicorn main:app --reload
```

(`--reload` restarts the worker automatically whenever a file changes —
handy for local development; drop it in production.)

Then open **http://localhost:8000** in your browser (gunicorn's default
port; pass `--bind 0.0.0.0:5000` if you want 5000 instead). The first launch
prints a short "warming up the recommendation engine" message while it
builds the similarity model — that's normal, and only happens once per
worker start.

## Deployment

In production, run the same command, just without `--reload`:

```bash
gunicorn main:app
```

Keeping the "Trending Today" refresh working under gunicorn needs one extra
piece: gunicorn can run several worker processes at once, each importing
`main.py` separately, so a scheduler started *inside* `main.py` would end up
running once per worker instead of once a day. To avoid that, the daily
refresh lives in its own standalone script instead:

```bash
python refresh_daily_popular_movies.py
```

This script runs forever (on purpose — its own internal scheduler wakes up
once every 24 hours to refresh the list, and the surrounding loop just keeps
the process alive in between). That means it needs to be deployed as an
**always-on process** alongside the web app — e.g. on Railway, as a second
service in the same project, with its start command set to the line above.
It is **not** a fit for a "Cron Job"-style service, since those expect the
command to finish and exit, not run indefinitely.

## Notes

- The recommendation model, the search index, and the "Trending Today" cache
  all live in memory and are rebuilt when the server restarts — there's
  nothing to keep in sync by hand.
- If a signal has no data yet (e.g. you haven't run the keyword-fetching step
  for older movies), the engine doesn't crash — that one signal just quietly
  contributes nothing until real data is there.
