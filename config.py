# config.py — this is the single place all the app's secret keys and connection
# settings live. Nothing here is hardcoded on purpose: the actual values come from
# a ".env" file that sits next to this one (and is never committed to GitHub —
# check .gitignore). If you're setting this project up fresh, copy ".env.example"
# to ".env" and fill in your own values.
import os
from dotenv import load_dotenv
import mysql.connector

load_dotenv()  # reads the ".env" file and makes its values available via os.getenv()

# TMDB (The Movie Database) API key — get a free one at
# https://www.themoviedb.org/settings/api
TMDB_API_KEY = os.getenv("TMDB_API_KEY")
TMDB_BASE_URL = "https://api.themoviedb.org/3"

# MySQL connection settings, read from the environment so the same code works
# whether the database is running on your laptop or on a hosting provider.
DB_CONFIG = {
    "host": os.getenv("MYSQLHOST"),
    "port": int(os.getenv("MYSQLPORT")),
    "user": os.getenv("MYSQLUSER"),
    "password": os.getenv("MYSQLPASSWORD"),
    "database": os.getenv("MYSQLDATABASE"),
}

# Flask uses this to sign session cookies (keeps login sessions tamper-proof).
# SECRET_KEY must be set in the environment, especially in production.
SECRET_KEY = os.environ["SECRET_KEY"]

# A connection pool keeps a handful of MySQL connections open and ready to reuse,
# instead of opening a brand new connection (which is slow — it involves a TCP
# handshake and a login) every single time a route needs to talk to the database.
cnxpool = mysql.connector.pooling.MySQLConnectionPool(
    pool_name="mypool",
    pool_size=5,
    **DB_CONFIG
)
