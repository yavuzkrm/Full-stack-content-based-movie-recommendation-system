from config import cnxpool


def get_db():
    """Borrows a connection from the shared pool (see config.py)."""
    return cnxpool.get_connection()


def _movies_for_person(link_table, person_name, top_n):
    """Shared query behind both filmography lookups below: finds a person by
    their exact name in `people`, then returns their highest-rated movies via
    the given link table (movie_cast for actors, movie_directors for
    directors). Returns an empty list if nobody by that name exists."""
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id FROM people WHERE name = %s", (person_name,))
        person = cursor.fetchone()
        if not person:
            return []

        cursor.execute(f"""
            SELECT m.id, m.title, m.poster_path, m.vote_avg
            FROM {link_table} l
            JOIN movies m ON l.movie_id = m.id
            WHERE l.person_id = %s
            ORDER BY m.vote_avg DESC
            LIMIT %s
        """, (person["id"], top_n))
        return cursor.fetchall()
    except Exception as e:
        print(f"Error fetching movies from {link_table}: {e}")
        return []
    finally:
        cursor.close()
        conn.close()


def movies_by_cast_member(person_name, top_n=50):
    """An actor's top_n highest-rated movies in the catalogue."""
    return _movies_for_person("movie_cast", person_name, top_n)


def movies_by_director(person_name, top_n=50):
    """A director's top_n highest-rated movies in the catalogue."""
    return _movies_for_person("movie_directors", person_name, top_n)
