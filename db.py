"""
Database Connection Pool Manager (Neon PostgreSQL)
Provides thread-safe connection pooling for sub-10ms query execution across:
- server.py (Starlette REST API & Webhooks)
- task_bot.py (Task management & Reminders)
- yandex_alice.py (Token retrieval & smart home settings)
"""

import os
import sys
import threading
from typing import Optional
from dotenv import load_dotenv

load_dotenv()
if not os.getenv("DATABASE_URL"):
    parent_env = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
    if os.path.exists(parent_env):
        load_dotenv(parent_env)
if not os.getenv("DATABASE_URL") and os.path.exists("E:/Documents/Lider/.env"):
    load_dotenv("E:/Documents/Lider/.env")

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

_pool = None
_pool_lock = threading.Lock()


class PooledConnectionWrapper:
    """
    Wraps a psycopg2 connection checked out from ThreadedConnectionPool.
    When .close() is called, returns the connection back to the pool instead of terminating the socket.
    """
    def __init__(self, conn, pool):
        self._conn = conn
        self._pool = pool
        self._returned = False

    def close(self):
        if not self._returned and self._pool and self._conn:
            self._returned = True
            try:
                if not self._conn.closed:
                    self._conn.rollback()
                self._pool.putconn(self._conn)
            except Exception as e:
                try:
                    self._pool.putconn(self._conn, close=True)
                except Exception:
                    pass
        elif not self._returned and self._conn:
            self._returned = True
            try:
                self._conn.close()
            except Exception:
                pass

    def __enter__(self):
        return self._conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __getattr__(self, name):
        return getattr(self._conn, name)


def get_pool():
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                db_url = os.getenv("DATABASE_URL")
                if db_url:
                    try:
                        import psycopg2.pool
                        # minconn=1, maxconn=10: optimal for Render container and Neon serverless
                        _pool = psycopg2.pool.ThreadedConnectionPool(minconn=1, maxconn=10, dsn=db_url)
                        print("[DB Pool] ThreadedConnectionPool initialized (1-10 connections)")
                    except Exception as e:
                        print(f"[DB Pool] Initialization error: {e}")
    return _pool


def get_db_connection():
    """
    Retrieves an active connection from the pool.
    Returns PooledConnectionWrapper whose .close() returns connection to pool.
    Falls back to direct connection if pool fails.
    """
    pool = get_pool()
    if pool:
        try:
            conn = pool.getconn()
            if conn.closed != 0:
                pool.putconn(conn, close=True)
                conn = pool.getconn()
            conn.set_client_encoding('UTF8')
            return PooledConnectionWrapper(conn, pool)
        except Exception as e:
            print(f"[DB Pool] Warning getting conn from pool: {e}")

    # Fallback to direct connect
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        try:
            import psycopg2
            conn = psycopg2.connect(db_url)
            conn.set_client_encoding('UTF8')
            return PooledConnectionWrapper(conn, None)
        except Exception as e:
            print(f"[DB] Direct connection error: {e}")
    return None


get_db = get_db_connection


def close_pool():
    """Closes all connections in the pool on server shutdown."""
    global _pool
    with _pool_lock:
        if _pool is not None:
            try:
                _pool.closeall()
                print("[DB Pool] Connection pool closed.")
            except Exception as e:
                print(f"[DB Pool] Error closing pool: {e}")
            _pool = None
