"""
storage/db_pool.py — Connection Pool para SQLite
=================================================
Resuelve el problema de "database is locked" bajo concurrencia
(hilo principal + CuriosidadPasiva + InvestigacionNocturna).

Uso recomendado (opcional, el sistema funciona sin él):
    from storage.db_pool import get_pool
    with get_pool().get(db_path) as conn:
        conn.execute(...)
        # commit automático al salir del with

El pool mantiene hasta MAX_CONNS conexiones por db_path.
Cada conexión tiene WAL + timeout configurado para evitar locks.
"""

import sqlite3
import threading
from contextlib import contextmanager
from queue import Queue, Empty

MAX_CONNS = 5
_pools: dict = {}
_pools_lock = threading.Lock()


class SQLitePool:
    def __init__(self, db_path: str, size: int = MAX_CONNS):
        self.db_path = db_path
        self._pool: Queue = Queue(maxsize=size)
        for _ in range(size):
            self._pool.put(self._new_conn())

    def _new_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            timeout=30,
        )
        conn.text_factory = str
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=10000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def get(self):
        """Context manager: obtiene conexión, hace commit al salir, la devuelve al pool."""
        try:
            conn = self._pool.get(timeout=10)
        except Empty:
            # Pool agotado — crear conexión temporal
            conn = self._new_conn()
            temp = True
        else:
            temp = False

        try:
            yield conn
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            if temp:
                conn.close()
            else:
                self._pool.put(conn)


def get_pool(db_path: str) -> SQLitePool:
    """Retorna (o crea) el pool singleton para un db_path dado."""
    if db_path not in _pools:
        with _pools_lock:
            if db_path not in _pools:
                _pools[db_path] = SQLitePool(db_path)
    return _pools[db_path]
