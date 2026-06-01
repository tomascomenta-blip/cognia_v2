"""
tests/test_fase2.py
===================
Tests de Fase 2: EpisodicMemory, NarrativeThread, VectorCache, _phase_decay.

Usa SQLite en memoria (:memory:) — sin dependencia de DB en disco.
Ejecutar con: python run_tests.py   (desde la raíz del proyecto)
"""

import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _create_schema(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS episodic_memory (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp       TEXT    NOT NULL,
            observation     TEXT    NOT NULL,
            label           TEXT    DEFAULT '',
            vector          TEXT,
            confidence      REAL    DEFAULT 0.5,
            importance      REAL    DEFAULT 1.0,
            emotion_score   REAL    DEFAULT 0.0,
            emotion_label   TEXT    DEFAULT 'neutral',
            surprise        REAL    DEFAULT 0.0,
            last_access     TEXT,
            access_count    INTEGER DEFAULT 0,
            forgotten       INTEGER DEFAULT 0,
            review_count    INTEGER DEFAULT 0,
            next_review     TEXT,
            context_tags    TEXT    DEFAULT '[]',
            feedback_weight REAL    DEFAULT 1.0
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ts ON episodic_memory(timestamp)")
    conn.commit()


def _insert(conn, observation, label="test", vector=None, timestamp=None,
            importance=1.0, emotion_score=0.0, emotion_label="neutral",
            forgotten=0, access_count=0, last_access=None):
    if vector is None:
        vector = [0.1] * 8
    ts = timestamp or datetime.now().isoformat()
    la = last_access or ts
    conn.execute("""
        INSERT INTO episodic_memory
        (timestamp, observation, label, vector, confidence, importance,
         emotion_score, emotion_label, surprise, last_access, access_count, forgotten)
        VALUES (?, ?, ?, ?, 0.7, ?, ?, ?, 0.0, ?, ?, ?)
    """, (ts, observation, label, json.dumps(vector), importance,
          emotion_score, emotion_label, la, access_count, forgotten))
    conn.commit()
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def _vec(seed: float, dim: int = 8) -> list:
    import math
    v = [seed + i * 0.01 for i in range(dim)]
    norm = math.sqrt(sum(x * x for x in v))
    return [x / norm for x in v]


# ══════════════════════════════════════════════════════════════════════════════
# TESTS: EpisodicMemory.get_in_window
# ══════════════════════════════════════════════════════════════════════════════

class TestGetInWindow:

    def _em(self, conn):
        from cognia.memory.episodic import EpisodicMemory
        em  = EpisodicMemory(":memory:")
        ctx = patch("cognia.memory.episodic.db_connect", return_value=conn)
        return em, ctx

    def test_retorna_episodios_dentro_de_ventana(self):
        conn = sqlite3.connect(":memory:")
        _create_schema(conn)
        now = datetime.now()
        _insert(conn, "dentro",  timestamp=(now - timedelta(hours=1)).isoformat())
        _insert(conn, "fuera",   timestamp=(now - timedelta(hours=5)).isoformat())
        em, ctx = self._em(conn)
        with ctx:
            result = em.get_in_window(now.isoformat(), window_hours=2.0)
        obs = [r["observation"] for r in result]
        assert "dentro" in obs
        assert "fuera"  not in obs

    def test_incluye_episodio_central(self):
        conn = sqlite3.connect(":memory:")
        _create_schema(conn)
        ts = datetime.now().isoformat()
        _insert(conn, "exacto", timestamp=ts)
        em, ctx = self._em(conn)
        with ctx:
            result = em.get_in_window(ts, window_hours=0.1)
        assert len(result) >= 1
        assert result[0]["observation"] == "exacto"

    def test_excluye_forgotten_por_defecto(self):
        conn = sqlite3.connect(":memory:")
        _create_schema(conn)
        ts = datetime.now().isoformat()
        _insert(conn, "olvidado",    timestamp=ts, forgotten=1)
        _insert(conn, "no olvidado", timestamp=ts, forgotten=0)
        em, ctx = self._em(conn)
        with ctx:
            result = em.get_in_window(ts)
        obs = [r["observation"] for r in result]
        assert "olvidado"    not in obs
        assert "no olvidado" in obs

    def test_include_forgotten_true(self):
        conn = sqlite3.connect(":memory:")
        _create_schema(conn)
        ts = datetime.now().isoformat()
        _insert(conn, "olvidado", timestamp=ts, forgotten=1)
        em, ctx = self._em(conn)
        with ctx:
            result = em.get_in_window(ts, include_forgotten=True)
        assert any(r["observation"] == "olvidado" for r in result)

    def test_respeta_limit(self):
        conn = sqlite3.connect(":memory:")
        _create_schema(conn)
        ts = datetime.now().isoformat()
        for i in range(10):
            _insert(conn, f"ep_{i}", timestamp=ts)
        em, ctx = self._em(conn)
        with ctx:
            result = em.get_in_window(ts, limit=3)
        assert len(result) <= 3

    def test_retorna_lista_vacia_sin_resultados(self):
        conn = sqlite3.connect(":memory:")
        _create_schema(conn)
        ts = datetime.now().isoformat()
        em, ctx = self._em(conn)
        with ctx:
            result = em.get_in_window(ts, window_hours=0.001)
        assert result == []

    def test_estructura_dict_completa(self):
        conn = sqlite3.connect(":memory:")
        _create_schema(conn)
        ts = datetime.now().isoformat()
        _insert(conn, "obs_x", label="etiqueta", timestamp=ts,
                importance=1.5, emotion_score=0.3, emotion_label="alegria")
        em, ctx = self._em(conn)
        with ctx:
            result = em.get_in_window(ts)
        assert len(result) == 1
        ep = result[0]
        for k in ("id", "observation", "label", "timestamp",
                  "confidence", "importance", "emotion_score",
                  "emotion_label", "surprise"):
            assert k in ep, f"Falta clave: {k}"
        assert ep["label"]         == "etiqueta"
        assert ep["importance"]    == pytest.approx(1.5)
        assert ep["emotion_score"] == pytest.approx(0.3)

    def test_orden_cronologico(self):
        conn = sqlite3.connect(":memory:")
        _create_schema(conn)
        now = datetime.now()
        ts1 = (now - timedelta(minutes=90)).isoformat()
        ts2 = (now - timedelta(minutes=60)).isoformat()
        ts3 = (now - timedelta(minutes=30)).isoformat()
        for ts in (ts3, ts1, ts2):
            _insert(conn, f"ep", timestamp=ts)
        em, ctx = self._em(conn)
        with ctx:
            result = em.get_in_window(now.isoformat(), window_hours=2.0)
        timestamps = [r["timestamp"] for r in result]
        assert timestamps == sorted(timestamps)


# ══════════════════════════════════════════════════════════════════════════════
# TESTS: NarrativeThread.build_thread
# ══════════════════════════════════════════════════════════════════════════════

class TestNarrativeThread:

    def _patches(self, conn):
        p1 = patch("cognia.memory.narrative.db_connect", return_value=conn)
        p2 = patch("cognia.memory.episodic.db_connect",  return_value=conn)
        return p1, p2

    def _conn(self):
        conn = sqlite3.connect(":memory:")
        _create_schema(conn)
        return conn

    def test_build_thread_retorna_semilla(self):
        conn = self._conn()
        ts = datetime.now().isoformat()
        seed_id = _insert(conn, "semilla", vector=_vec(0.5), timestamp=ts)
        from cognia.memory.narrative import NarrativeThread
        nt = NarrativeThread(":memory:", sim_threshold=0.0)
        p1, p2 = self._patches(conn)
        with p1, p2:
            thread = nt.build_thread(seed_id)
        assert len(thread) >= 1
        assert any(ep["id"] == seed_id for ep in thread)

    def test_build_thread_seed_inexistente(self):
        conn = self._conn()
        from cognia.memory.narrative import NarrativeThread
        nt = NarrativeThread(":memory:")
        p1, p2 = self._patches(conn)
        with p1, p2:
            thread = nt.build_thread(9999)
        assert thread == []

    def test_build_thread_filtra_por_similitud(self):
        conn = self._conn()
        ts = datetime.now().isoformat()
        seed_id = _insert(conn, "semilla",  vector=_vec(0.5),  timestamp=ts)
        _insert(conn, "similar",  vector=_vec(0.51), timestamp=ts)
        dist_id = _insert(conn, "distinto", vector=_vec(0.0),  timestamp=ts)
        from cognia.memory.narrative import NarrativeThread
        nt = NarrativeThread(":memory:", sim_threshold=0.99)
        p1, p2 = self._patches(conn)
        with p1, p2:
            thread = nt.build_thread(seed_id)
        ids = [ep["id"] for ep in thread]
        assert seed_id in ids
        assert dist_id not in ids

    def test_build_thread_orden_cronologico(self):
        conn = self._conn()
        now = datetime.now()
        v   = _vec(0.5)
        _insert(conn, "p", vector=v, timestamp=(now - timedelta(minutes=50)).isoformat())
        id2 = _insert(conn, "s", vector=v, timestamp=(now - timedelta(minutes=30)).isoformat())
        _insert(conn, "t", vector=v, timestamp=now.isoformat())
        from cognia.memory.narrative import NarrativeThread
        nt = NarrativeThread(":memory:", sim_threshold=0.0)
        p1, p2 = self._patches(conn)
        with p1, p2:
            thread = nt.build_thread(id2)
        ts_list = [ep["timestamp"] for ep in thread]
        assert ts_list == sorted(ts_list)


# ══════════════════════════════════════════════════════════════════════════════
# TESTS: VectorCache — hash XOR
# ══════════════════════════════════════════════════════════════════════════════

class TestVectorCacheHash:

    def _shared_db(self):
        """DB en archivo temporal compartida entre conexiones (evita close() que mata :memory:)."""
        tf = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tf.close()
        path = tf.name
        conn = sqlite3.connect(path)
        _create_schema(conn)
        conn.commit()
        return path, conn

    def test_hash_xor_es_determinista(self):
        path, conn = self._shared_db()
        try:
            ts = datetime.now().isoformat()
            for i in range(5):
                _insert(conn, f"ep_{i}", timestamp=ts, importance=1.0 + i * 0.1)
            conn.close()

            from cognia.memory.episodic_fast import VectorCache
            cache = VectorCache(path)
            cache._hash_cache_ts = 0.0
            h1 = cache._get_db_hash()
            cache._hash_cache_ts = 0.0
            h2 = cache._get_db_hash()

            assert h1 == h2
            assert h1 != 0
        finally:
            from storage.db_pool import close_pool
            close_pool(path)
            os.unlink(path)

    def test_hash_xor_cambia_con_nuevos_episodios(self):
        path, conn = self._shared_db()
        try:
            ts = datetime.now().isoformat()
            _insert(conn, "inicial", timestamp=ts, importance=1.0)
            conn.commit()

            from cognia.memory.episodic_fast import VectorCache
            cache = VectorCache(path)
            cache._hash_cache_ts = 0.0
            h1 = cache._get_db_hash()

            _insert(conn, "nuevo", timestamp=ts, importance=2.0)
            conn.commit()
            cache._hash_cache_ts = 0.0
            h2 = cache._get_db_hash()

            assert h1 != h2
        finally:
            conn.close()
            from storage.db_pool import close_pool
            close_pool(path)
            os.unlink(path)

    def test_needs_rebuild_si_hash_cambia(self):
        from cognia.memory.episodic_fast import VectorCache
        cache = VectorCache(":memory:")
        cache._db_hash = 12345
        assert cache._needs_rebuild(99999) is True

    def test_no_needs_rebuild_si_hash_igual(self):
        import numpy as np
        from cognia.memory.episodic_fast import VectorCache
        cache = VectorCache(":memory:")
        cache._matrix  = np.zeros((1, 8))
        cache._db_hash = 42
        assert cache._needs_rebuild(42) is False


# ══════════════════════════════════════════════════════════════════════════════
# TESTS: ConsolidationEngine._phase_decay
# Usa archivo temporal porque _phase_decay cierra su propia conn.
# ══════════════════════════════════════════════════════════════════════════════

def _temp_db_with_data(setup_fn):
    """Crea DB temporal, llama setup_fn(conn), retorna (path, engine)."""
    import threading
    from cognia.consolidation_engine import ConsolidationEngine

    tf = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tf.close()
    path = tf.name

    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE episodic_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT DEFAULT '', observation TEXT DEFAULT '',
            importance REAL DEFAULT 1.5, emotion_score REAL DEFAULT 0.0,
            access_count INTEGER DEFAULT 0, last_access TEXT,
            forgotten INTEGER DEFAULT 0, confidence REAL DEFAULT 0.5,
            feedback_weight REAL DEFAULT 1.0, label TEXT DEFAULT '',
            vector TEXT, surprise REAL DEFAULT 0.0,
            review_count INTEGER DEFAULT 0, next_review TEXT,
            context_tags TEXT DEFAULT '[]'
        )
    """)
    conn.execute("""
        CREATE TABLE semantic_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            concept TEXT UNIQUE, confidence REAL DEFAULT 0.5,
            support INTEGER DEFAULT 1, emotion_avg REAL DEFAULT 0.0
        )
    """)
    conn.execute("""
        CREATE TABLE knowledge_graph (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT, predicate TEXT, object TEXT,
            weight REAL DEFAULT 1.0, created TEXT
        )
    """)
    conn.commit()
    setup_fn(conn)
    conn.close()

    engine = object.__new__(ConsolidationEngine)
    engine.db_path = path
    engine._lock   = threading.Lock()
    return path, engine


class TestPhaseDecay:

    def test_decay_reduce_importancia(self):
        old_ts = (datetime.now() - timedelta(days=20)).isoformat()

        def setup(conn):
            conn.execute(
                "INSERT INTO episodic_memory (timestamp, observation, importance, "
                "emotion_score, access_count, last_access, forgotten) "
                "VALUES (?, 'viejo', 2.0, 0.0, 0, ?, 0)", (old_ts, old_ts))
            conn.commit()

        path, engine = _temp_db_with_data(setup)
        try:
            decayed = engine._phase_decay()
            _c = sqlite3.connect(path)
            row = _c.execute("SELECT importance FROM episodic_memory").fetchone()
            _c.close()
            assert decayed >= 1
            assert row[0] < 2.0
        finally:
            os.unlink(path)

    def test_decay_alta_emocion_decae_mas_lento(self):
        old_ts = (datetime.now() - timedelta(days=20)).isoformat()

        def setup(conn):
            conn.execute(
                "INSERT INTO episodic_memory (timestamp, observation, importance, "
                "emotion_score, access_count, last_access, forgotten) "
                "VALUES (?, 'emocional', 2.0, 0.8, 0, ?, 0)", (old_ts, old_ts))
            conn.execute(
                "INSERT INTO episodic_memory (timestamp, observation, importance, "
                "emotion_score, access_count, last_access, forgotten) "
                "VALUES (?, 'neutro', 2.0, 0.0, 0, ?, 0)", (old_ts, old_ts))
            conn.commit()

        path, engine = _temp_db_with_data(setup)
        try:
            engine._phase_decay()
            _c = sqlite3.connect(path)
            rows = {r[0]: r[1] for r in _c.execute(
                "SELECT observation, importance FROM episodic_memory"
            ).fetchall()}
            _c.close()
            assert rows["emocional"] > rows["neutro"]
        finally:
            os.unlink(path)

    def test_decay_sin_accesos_decae_mas_rapido(self):
        old_ts = (datetime.now() - timedelta(days=20)).isoformat()

        def setup(conn):
            conn.execute(
                "INSERT INTO episodic_memory (timestamp, observation, importance, "
                "emotion_score, access_count, last_access, forgotten) "
                "VALUES (?, 'nunca', 2.0, 0.0, 0, ?, 0)", (old_ts, old_ts))
            conn.execute(
                "INSERT INTO episodic_memory (timestamp, observation, importance, "
                "emotion_score, access_count, last_access, forgotten) "
                "VALUES (?, 'accedido', 2.0, 0.0, 5, ?, 0)", (old_ts, old_ts))
            conn.commit()

        path, engine = _temp_db_with_data(setup)
        try:
            engine._phase_decay()
            _c = sqlite3.connect(path)
            rows = {r[0]: r[1] for r in _c.execute(
                "SELECT observation, importance FROM episodic_memory"
            ).fetchall()}
            _c.close()
            assert rows["nunca"] < rows["accedido"]
        finally:
            os.unlink(path)

    def test_decay_no_toca_episodios_recientes(self):
        reciente = datetime.now().isoformat()

        def setup(conn):
            conn.execute(
                "INSERT INTO episodic_memory (timestamp, observation, importance, "
                "emotion_score, access_count, last_access, forgotten) "
                "VALUES (?, 'reciente', 2.0, 0.0, 0, ?, 0)", (reciente, reciente))
            conn.commit()

        path, engine = _temp_db_with_data(setup)
        try:
            decayed = engine._phase_decay()
            assert decayed == 0
        finally:
            os.unlink(path)

    def test_decay_no_baja_del_minimo(self):
        from cognia.consolidation_engine import DECAY_IMPORTANCE_MIN
        old_ts = (datetime.now() - timedelta(days=200)).isoformat()

        def setup(conn):
            conn.execute(
                "INSERT INTO episodic_memory (timestamp, observation, importance, "
                "emotion_score, access_count, last_access, forgotten) "
                "VALUES (?, 'en_minimo', ?, 0.0, 0, ?, 0)",
                (old_ts, DECAY_IMPORTANCE_MIN, old_ts))
            conn.commit()

        path, engine = _temp_db_with_data(setup)
        try:
            engine._phase_decay()
            _c = sqlite3.connect(path)
            row = _c.execute("SELECT importance FROM episodic_memory").fetchone()
            _c.close()
            assert row[0] >= DECAY_IMPORTANCE_MIN
        finally:
            os.unlink(path)
