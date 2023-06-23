import psycopg2
from contextlib import contextmanager
from os import environ
import logging

log = logging.getLogger("postgres")

@contextmanager
def db_get_cursor():
    conn = psycopg2.connect(
        host=environ["POSTGRES_HOST"],
        user=environ["POSTGRES_USER"],
        password=environ["POSTGRES_PASSWORD"],
        dbname=environ["POSTGRES_DB"],
        port=environ["POSTGRES_PORT"]
    )
    cursor = conn.cursor()
    try:
        yield cursor
        conn.commit()
    except psycopg2.DatabaseError as err:
        log.exception("Error in cursor: %s", err.args)
    finally:
        conn.close()
