from config import cnxpool

def get_db():

    return cnxpool.get_connection()

def movies_by_cast_member(person_name, top_n=50):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)



    try:
        cursor.execute(f"""
            SELECT id FROM people WHERE name = %s
        """, (person_name,))
        person_id = cursor.fetchone()
        if not person_id:
            return []
        person_id = person_id['id']

        cursor.execute(f"""
            SELECT m.id, m.title, m.poster_path, m.vote_avg
            FROM movie_cast mc
            JOIN movies m ON mc.movie_id = m.id
            WHERE mc.person_id = %s
            ORDER BY m.vote_avg DESC
            LIMIT %s
        """, (person_id, top_n))
        return cursor.fetchall()
    except Exception as e:
        print(f" Error fetching cast member movies: {e}")
        return []
    finally:
        cursor.close()
        conn.close()

def movies_by_director(person_name, top_n=50):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute(f"""
            SELECT id FROM people WHERE name = %s
        """, (person_name,))
        person_id = cursor.fetchone()
        if not person_id:
            return []
        person_id = person_id['id']
        
        cursor.execute(f"""
            SELECT m.id, m.title, m.poster_path, m.vote_avg
            FROM movie_directors md
            JOIN movies m ON md.movie_id = m.id
            WHERE md.person_id = %s
            ORDER BY m.vote_avg DESC
            LIMIT %s
        """, (person_id, top_n))
        return cursor.fetchall()
    except Exception as e:
        print(f" Error fetching director movies: {e}")
        return []
    finally:
        cursor.close()
        conn.close()
