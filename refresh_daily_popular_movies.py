import time
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from data.fetch_daily_popular_movies import fetch_popular_movie


def refresh_popular_movies():
    """Runs once a day (see the scheduler at the bottom of this file): pulls
    a fresh "trending today" list from TMDB. The old list isn't cleared until
    the new one is ready — see fetch_popular_movie()'s docstring for why that
    matters (it's what keeps "Trending Today" from going visibly empty on the
    homepage during the refresh)."""
    print("Refreshing today's popular movies list...")
    fetch_popular_movie()
    print("Done.")


if __name__ == "__main__":
    scheduler = BackgroundScheduler()
    # next_run_time=datetime.now() makes the FIRST refresh fire immediately on
    # startup, instead of APScheduler's default "interval" behaviour of
    # waiting a full 24 hours for the first run. Without this, every time the
    # process restarts (a redeploy, a crash, a Railway maintenance restart...)
    # "Trending Today" would silently stay empty/stale for up to a day before
    # anyone noticed.
    scheduler.add_job(refresh_popular_movies, "interval", hours=24, next_run_time=datetime.now())
    scheduler.start()
    print("Scheduler started — refreshing the popular movies list now, then every 24 hours.")

    # BackgroundScheduler runs its job on a daemon thread, which means it dies
    # the instant this main thread reaches the end of the script — without
    # something here to keep the process alive, the scheduled job would never
    # actually get a chance to fire. This loop just keeps the process running
    # forever (sleeping most of the time, so it costs essentially nothing),
    # until Railway sends a shutdown signal (e.g. on redeploy), at which point
    # we shut the scheduler down cleanly instead of just getting killed.
    try:
        while True:
            time.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
