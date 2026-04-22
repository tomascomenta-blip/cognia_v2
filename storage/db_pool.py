"""
storage/db_pool.py — Connection Pool para SQLite (v2)
=====================================================
CAMBIOS v2 respecto al original:
  - `get_pool()` ahora acepta db_path opcional (usa DB_PATH por defecto)
  - `db_connect_pooled()` es un drop-in replacement de `db_connect()`:
    devuelve una conexión del pool envuelta en un PooledConnection que
    hace commit+release al llamar a .close(), sin romper el código existente.
  - `_PooledConnection` permite usar el patrón antiguo conn/conn.close()
    pero internamente devuelve la conexión al pool en vez de cerrarla.

USO EN MÓDULOS EXISTENTES (cambio mínimo):
    # Antes:
    from ..database import db_connect
    conn = db_connect(self.db)
    ...
    conn.close()

    # Después (1 línea cambiada):
    from storage.db_pool import db_connect_pooled as db_connect
    conn = db_connect(self.db)
    ...
    conn.close()  # hace commit + devuelve al pool, no cierra la conexión física

USO RECOMENDADO CON CONTEXT MANAGER:
    from storage.db_pool import get_pool
    with get_pool(db_path).get() as conn:
        conn.execute(...)
        # commit automático al salir del with

DIAGNÓSTICO:
    from storage.db_pool import pool_stats
    print(pool_stats())  # tamaño de cada pool activo
"""

import sqlite3
import threading
from contextlib import contextmanager
from queue import Queue, Empty
from typing import Optional

MAX_CONNS = 5
_pools: dict = {}
_pools_lock = threading.Lock()


# ══════════════════════════════════════════════════════════════════════
# POOL PRINCIPAL
# ══════════════════════════════════════════════════════════════════════

class SQLitePool:
    def __init__(self, db_path: str, size: int = MAX_CONNS):
        self.db_path = db_path
        self._size   = size
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
        """
        Context manager: obtiene conexión, hace commit al salir, la devuelve al pool.
        Si el pool está agotado, crea una conexión temporal (no queda en el pool).
        """
        temp = False
        try:
            conn = self._pool.get(timeout=10)
        except Empty:
            conn = self._new_conn()
            temp = True

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

    def acquire(self) -> sqlite3.Connection:
        """Obtiene una conexión sin context manager. Llamar release() cuando termines."""
        try:
            return self._pool.get(timeout=10)
        except Empty:
            return self._new_conn()

    def release(self, conn: sqlite3.Connection, commit: bool = True):
        """Devuelve una conexión obtenida con acquire()."""
        try:
            if commit:
                conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
        try:
            self._pool.put_nowait(conn)
        except Exception:
            conn.close()  # pool lleno — cerrar la sobrante

    @property
    def size(self) -> int:
        return self._size


# ══════════════════════════════════════════════════════════════════════
# POOLED CONNECTION — wrapper drop-in para conn.close() existente
# ══════════════════════════════════════════════════════════════════════

class _PooledConnection:
    """
    Envuelve una sqlite3.Connection y redirige .close() al pool en lugar
    de cerrar la conexión física.

    Permite usar el patrón antiguo:
        conn = db_connect(path)
        conn.execute(...)
        conn.commit()
        conn.close()    ← devuelve al pool, no cierra

    Todos los demás métodos/atributos se delegan directamente.
    """

    def __init__(self, raw_conn: sqlite3.Connection, pool: SQLitePool):
        self._conn  = raw_conn
        self._pool  = pool
        self._closed = False

    def close(self):
        if not self._closed:
            self._closed = True
            self._pool.release(self._conn, commit=False)  # no commit doble

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def __enter__(self):
        return self._conn.__enter__()

    def __exit__(self, *args):
        result = self._conn.__exit__(*args)
        self.close()
        return result

    def cursor(self):
        return self._conn.cursor()

    def execute(self, sql, params=()):
        return self._conn.execute(sql, params)

    def executemany(self, sql, params):
        return self._conn.executemany(sql, params)

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()


# ══════════════════════════════════════════════════════════════════════
# API PÚBLICA
# ══════════════════════════════════════════════════════════════════════

def get_pool(db_path: str = None) -> SQLitePool:
    """
    Retorna (o crea) el pool singleton para un db_path dado.
    Si db_path es None, usa cognia/config.DB_PATH.
    """
    if db_path is None:
        try:
            from cognia.config import DB_PATH
            db_path = DB_PATH
        except ImportError:
            db_path = "cognia_memory.db"

    if db_path not in _pools:
        with _pools_lock:
            if db_path not in _pools:
                _pools[db_path] = SQLitePool(db_path)
    return _pools[db_path]


def db_connect_pooled(db_path: str = None) -> _PooledConnection:
    """
    Drop-in replacement de db_connect().
    Devuelve una _PooledConnection que se comporta como sqlite3.Connection
    pero devuelve la conexión al pool cuando se llama .close().

    USO:
        from storage.db_pool import db_connect_pooled as db_connect
        conn = db_connect(self.db)
        conn.execute(...)
        conn.commit()
        conn.close()  # ← devuelve al pool
    """
    pool = get_pool(db_path)
    raw  = pool.acquire()
    return _PooledConnection(raw, pool)


def pool_stats() -> dict:
    """Diagnóstico: tamaño y conexiones disponibles en cada pool activo."""
    stats = {}
    for path, pool in _pools.items():
        stats[path] = {
            "size": pool.size,
            "available": pool._pool.qsize(),
        }
    return stats
