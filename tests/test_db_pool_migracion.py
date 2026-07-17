# -*- coding: utf-8 -*-
"""Regresion: los call-sites por-operacion usan el pool, no sqlite3.connect.

Deuda tecnica cazada 2026-07-16 (regla del repo: sin sqlite3.connect directo
-> storage/db_pool): thought_cache, self_improvement, scale_manager,
goal_and_pattern_engine, knowledge_integrator, data_generator y los 4 modulos
del coordinator abrian conexiones directas (algunas SIN WAL ni timeout) que
competian con las del pool sobre los mismos .db -> "database is locked"
esporadicos multi-hilo. Los :memory: quedan directos a proposito (una DB en
memoria es por-conexion; poolearla cambiaria la semantica).

Ademas: SQLitePool.release ahora resetea row_factory (varios sites setean
sqlite3.Row; sin el reset la mutacion se filtraba al proximo usuario).
"""
import sqlite3

import storage.db_pool as db_pool


def test_release_resetea_row_factory(tmp_path):
    db = str(tmp_path / "x.db")
    conn = db_pool.db_connect_pooled(db)
    conn.row_factory = sqlite3.Row
    # el proxy delega la ESCRITURA a la conexion real (bug cazado: el set
    # quedaba en el wrapper y las filas volvian como tuplas)
    assert conn._conn.row_factory is sqlite3.Row
    conn.close()  # devuelve al pool
    conn2 = db_pool.db_connect_pooled(db)
    try:
        assert conn2.row_factory is None, (
            "row_factory de un usuario anterior se filtro por el pool")
    finally:
        conn2.close()
        db_pool.close_pool(db)


def test_coordinator_registry_pasa_por_el_pool(tmp_path):
    from coordinator.registry import NodeRegistry
    db = str(tmp_path / "registry.db")
    reg = NodeRegistry(db_path=db)  # _init_db ejecuta el schema via _conn()
    try:
        stats = db_pool.pool_stats()
        assert any(db in k for k in stats), (
            f"NodeRegistry no paso por el pool; pools activos: {list(stats)}")
    finally:
        db_pool.close_pool(db)


def test_knowledge_integrator_db_es_pooled(tmp_path):
    from cognia.research_engine import knowledge_integrator as ki
    db = str(tmp_path / "ki.db")
    conn = ki._db(db)
    try:
        assert isinstance(conn, db_pool._PooledConnection)
    finally:
        conn.close()
        db_pool.close_pool(db)


def test_sin_connect_directo_en_sites_migrados():
    """Pin estatico: que no vuelva el sqlite3.connect directo a estos sites."""
    import inspect
    import cognia.reasoning.thought_cache as tc
    import cognia.agents.self_improvement as si
    import cognia.scale_manager as sm
    import shattering.distillation.data_generator as dg
    for mod in (tc, si, sm, dg):
        src = inspect.getsource(mod)
        # unico connect tolerado: ':memory:' (por-instancia)
        for i, line in enumerate(src.splitlines(), 1):
            if "sqlite3.connect(" in line and ":memory:" not in line:
                raise AssertionError(f"{mod.__name__}:{i} volvio al connect directo: {line.strip()}")
