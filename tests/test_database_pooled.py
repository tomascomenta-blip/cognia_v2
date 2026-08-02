"""
tests/test_database_pooled.py — deuda 2026-07-16 saldada en database.py.

init_db y limpiar_episodios_ruido abren y cierran la conexion en la misma
funcion (el caso seguro para poolear), asi que migran de db_connect (conexiones
propias) a storage.db_pool.db_connect_pooled: close() devuelve la conexion al
pool en vez de cerrarla. El teardown cierra el pool antes de que pytest borre
el tmp_path (Windows-safe, mismo patron que test_consolidation_v3).
"""

import pytest

from cognia.database import init_db, limpiar_episodios_ruido
from storage import db_pool
from storage.db_pool import close_pool


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "database_pooled.db")
    yield path
    close_pool(path)


def test_init_db_usa_el_pool(db_path):
    init_db(db_path)
    # La conexion salio del pool del path (no de un sqlite3.connect propio)...
    assert db_path in db_pool._pools
    pool = db_pool._pools[db_path]
    # ...y volvio al pool completa (ninguna conexion fugada).
    assert pool._pool.qsize() == pool.size


def test_init_db_idempotente_y_migrado(db_path):
    init_db(db_path)
    init_db(db_path)   # segunda llamada: no debe romper
    with db_pool.get_pool(db_path).get() as conn:
        cols = {r[1] for r in conn.execute(
            "PRAGMA table_info(episodic_memory)").fetchall()}
        chat_cols = {r[1] for r in conn.execute(
            "PRAGMA table_info(chat_history)").fetchall()}
    # Las migraciones (antes bajo `with conn:`, ahora commit explicito porque
    # _PooledConnection.__exit__ devolveria la conexion al pool a mitad de
    # funcion) siguen aplicandose.
    assert "feedback_weight" in cols
    assert {"session_id", "cwd"} <= chat_cols


def test_limpiar_episodios_ruido_pooled(db_path):
    init_db(db_path)
    out = limpiar_episodios_ruido(db_path)
    assert set(out) == {"episodios_limpiados", "kg_triples_eliminados"}
    pool = db_pool._pools[db_path]
    assert pool._pool.qsize() == pool.size
