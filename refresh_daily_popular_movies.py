import time
from apscheduler.schedulers.background import BackgroundScheduler
from data.fetch_daily_popular_movies import fetch_popular_movie, truncate_popular_movie


def refresh_popular_movies():
    """Runs once a day (see the scheduler at the bottom of this file):
    wipes yesterday's "trending today" list and pulls a fresh one from TMDB."""
    print("Refreshing today's popular movies list...")
    truncate_popular_movie()
    fetch_popular_movie()
    print("Done.")


if __name__ == "__main__":
    scheduler = BackgroundScheduler()
    scheduler.add_job(refresh_popular_movies, "interval", hours=24)
    scheduler.start()
    print("Scheduler started — will refresh the popular movies list every 24 hours.")

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