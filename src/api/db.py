import os
from pathlib import Path
from threading import Lock
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool
from contextlib import contextmanager
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / "config" / ".env")

_pool = None
_pool_lock = Lock()


def connection_pool():
    """Open local connections on first use, not during application import."""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = ThreadedConnectionPool(
                    1, 10, os.environ["DATABASE_URL"], cursor_factory=RealDictCursor
                )
    return _pool


@contextmanager
def get_conn():
    pool = connection_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)
