"""
tests/test_consolidation.py
============================
Test suite for schema migration (database.py) and ConsolidationEngine phases.

Uses temporary SQLite files — no in-memory DB because some phases
open their own connections and need a real file path.
All temp files are cleaned up after each test.
"""

import json
import os
import sqlite3
import sys
import tempfile
import threading
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

def _full_schema(conn):
    """Create the complete episodic_memory schema (including feedback_weight)."""
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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_label ON episodic_memory(label)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_forgotten ON episodic_memory(forgotten)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS semantic_memory (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            concept      TEXT UNIQUE,
            confidence   REAL DEFAULT 0.5,
            support      INTEGER DEFAULT 1,
            emotion_avg  REAL DEFAULT 0.0,
            vector       TEXT,
            associations TEXT DEFAULT '{}'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS knowledge_graph (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            subject   TEXT, predicate TEXT, object TEXT,
            weight    REAL DEFAULT 1.0, created TEXT
        )
    """)
    conn.commit()


def _schema_without_feedback_weight(conn):
    """Simulate an old DB: full schema except feedback_weight column."""
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
            context_tags    TEXT    DEFAULT '[]'
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ts ON episodic_memory(timestamp)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_label ON episodic_memory(label)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_forgotten ON episodic_memory(forgotten)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS semantic_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            concept TEXT UNIQUE, confidence REAL DEFAULT 0.5,
            support INTEGER DEFAULT 1, emotion_avg REAL DEFAULT 0.0
        )
    """)
    conn.commit()


def _temp_db():
    """Return path of an empty temp file (caller must delete)."""
    tf = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tf.close()
    return tf.name


def _unlink_db(path: str) -> None:
    """Delete a SQLite DB and its WAL/SHM files safely on Windows.

    WAL mode creates -wal and -shm files that keep Windows file locks open.
    Switching back to DELETE journal mode checkpoints WAL before removal.
    """
    try:
        _c = sqlite3.connect(path)
        _c.execute("PRAGMA wal_checkpoint(FULL)")
        _c.execute("PRAGMA journal_mode=DELETE")
        _c.close()
    except Exception:
        pass
    for suffix in ("", "-wal", "-shm"):
        try:
            os.unlink(path + suffix)
        except FileNotFoundError:
            pass


def _days_ago_iso(n: int) -> str:
    return (datetime.now() - timedelta(days=n)).isoformat()


def _insert_episode(conn, *, observation="test", label="test",
                    vector=None, confidence=0.5, importance=1.0,
                    feedback_weight=1.0, access_count=0,
                    timestamp=None, forgotten=0):
    if vector is None:
        vector = [0.1] * 10
    ts = timestamp or datetime.now().isoformat()
    conn.execute("""
        INSERT INTO episodic_memory
        (timestamp, observation, label, vector, confidence, importance,
         feedback_weight, access_count, last_access, forgotten)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (ts, observation, label, json.dumps(vector),
          confidence, importance, feedback_weight, access_count, ts, forgotten))
    conn.commit()
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def _make_engine(db_path: str):
    """Create a ConsolidationEngine without calling __init__ (avoids _init_schema)."""
    from cognia.consolidation_engine import ConsolidationEngine
    eng = object.__new__(ConsolidationEngine)
    eng.db_path = db_path
    eng._lock   = threading.RLock()
    eng._light_cycle_count = 0
    eng._interval = 20
    # Run _init_schema so consolidation_log table exists
    eng._init_schema()
    return eng


# ─────────────────────────────────────────────────────────────────────
# Schema migration
# ─────────────────────────────────────────────────────────────────────

class TestInitDb:

    def test_fresh_db_has_feedback_weight_column(self):
        path = _temp_db()
        try:
            from cognia.database import init_db
            init_db(path)
            conn = sqlite3.connect(path)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(episodic_memory)").fetchall()}
            conn.close()
            assert "feedback_weight" in cols
        finally:
            os.unlink(path)

    def test_old_db_missing_column_gets_migrated(self):
        path = _temp_db()
        try:
            conn = sqlite3.connect(path)
            _schema_without_feedback_weight(conn)
            conn.close()

            from cognia.database import init_db
            init_db(path)

            conn = sqlite3.connect(path)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(episodic_memory)").fetchall()}
            conn.close()
            assert "feedback_weight" in cols
        finally:
            os.unlink(path)

    def test_migration_idempotent(self):
        """Running init_db twice should not raise."""
        path = _temp_db()
        try:
            from cognia.database import init_db
            init_db(path)
            init_db(path)   # second call
            conn = sqlite3.connect(path)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(episodic_memory)").fetchall()}
            conn.close()
            assert "feedback_weight" in cols
        finally:
            os.unlink(path)

    def test_schema_version_table_created(self):
        path = _temp_db()
        try:
            from cognia.database import init_db
            init_db(path)
            conn = sqlite3.connect(path)
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
            conn.close()
            assert "schema_version" in tables
        finally:
            os.unlink(path)


# ─────────────────────────────────────────────────────────────────────
# _phase_purge
# ─────────────────────────────────────────────────────────────────────

class TestPhasePurge:

    def _db_with_episode(self, **kwargs):
        path = _temp_db()
        conn = sqlite3.connect(path)
        _full_schema(conn)
        ep_id = _insert_episode(conn, **kwargs)
        conn.close()
        return path, ep_id

    def test_purge_marks_low_quality_episode_forgotten(self):
        old_ts = _days_ago_iso(10)
        path, ep_id = self._db_with_episode(
            observation="bad_ep", confidence=0.25, feedback_weight=0.20,
            access_count=0, timestamp=old_ts, label="other"
        )
        try:
            eng = _make_engine(path)
            purged = eng._phase_purge()
            _c = sqlite3.connect(path)
            row = _c.execute(
                "SELECT forgotten FROM episodic_memory WHERE id=?", (ep_id,)
            ).fetchone()
            _c.close()
            assert purged >= 1
            assert row[0] == 1
        finally:
            os.unlink(path)

    def test_purge_spares_recent_episodes(self):
        recent_ts = datetime.now().isoformat()
        path, ep_id = self._db_with_episode(
            confidence=0.25, feedback_weight=0.20, access_count=0,
            timestamp=recent_ts, label="other"
        )
        try:
            eng = _make_engine(path)
            purged = eng._phase_purge()
            _c = sqlite3.connect(path)
            row = _c.execute(
                "SELECT forgotten FROM episodic_memory WHERE id=?", (ep_id,)
            ).fetchone()
            _c.close()
            assert purged == 0
            assert row[0] == 0
        finally:
            os.unlink(path)

    def test_purge_spares_protected_labels(self):
        old_ts = _days_ago_iso(10)
        path, ep_id = self._db_with_episode(
            confidence=0.25, feedback_weight=0.20, access_count=0,
            timestamp=old_ts, label="feedback"
        )
        try:
            eng = _make_engine(path)
            purged = eng._phase_purge()
            _c = sqlite3.connect(path)
            row = _c.execute(
                "SELECT forgotten FROM episodic_memory WHERE id=?", (ep_id,)
            ).fetchone()
            _c.close()
            assert row[0] == 0
        finally:
            os.unlink(path)

    def test_purge_spares_high_confidence_episodes(self):
        old_ts = _days_ago_iso(10)
        path, ep_id = self._db_with_episode(
            confidence=0.90, feedback_weight=0.20, access_count=0,
            timestamp=old_ts, label="other"
        )
        try:
            eng = _make_engine(path)
            purged = eng._phase_purge()
            _c = sqlite3.connect(path)
            row = _c.execute(
                "SELECT forgotten FROM episodic_memory WHERE id=?", (ep_id,)
            ).fetchone()
            _c.close()
            assert row[0] == 0
        finally:
            os.unlink(path)


# ─────────────────────────────────────────────────────────────────────
# _phase_weaken
# ─────────────────────────────────────────────────────────────────────

class TestPhaseWeaken:

    def test_weaken_reduces_importance(self):
        path = _temp_db()
        try:
            conn = sqlite3.connect(path)
            _full_schema(conn)
            # feedback_weight in range (0.30, 0.45], importance > 0.3
            _insert_episode(conn, observation="weak_ep", importance=1.5,
                            feedback_weight=0.40, confidence=0.5)
            conn.close()

            eng = _make_engine(path)
            weakened = eng._phase_weaken()

            _c = sqlite3.connect(path)
            row = _c.execute("SELECT importance FROM episodic_memory").fetchone()
            _c.close()
            assert weakened >= 1
            assert row[0] < 1.5
        finally:
            os.unlink(path)

    def test_weaken_does_not_drop_below_minimum(self):
        from cognia.consolidation_engine import WEAKEN_IMPORTANCE_MIN
        path = _temp_db()
        try:
            conn = sqlite3.connect(path)
            _full_schema(conn)
            _insert_episode(conn, importance=WEAKEN_IMPORTANCE_MIN + 0.01,
                            feedback_weight=0.40, confidence=0.5)
            conn.close()

            eng = _make_engine(path)
            eng._phase_weaken()

            _c = sqlite3.connect(path)
            row = _c.execute("SELECT importance FROM episodic_memory").fetchone()
            _c.close()
            assert row[0] >= WEAKEN_IMPORTANCE_MIN
        finally:
            os.unlink(path)

    def test_weaken_skips_high_weight_episodes(self):
        path = _temp_db()
        try:
            conn = sqlite3.connect(path)
            _full_schema(conn)
            _insert_episode(conn, importance=1.5, feedback_weight=1.0)
            conn.close()

            eng = _make_engine(path)
            weakened = eng._phase_weaken()
            assert weakened == 0
        finally:
            os.unlink(path)


# ─────────────────────────────────────────────────────────────────────
# _phase_consolidate
# ─────────────────────────────────────────────────────────────────────

class TestPhaseConsolidate:

    def _similar_vectors(self):
        """Two normalised vectors with cosine similarity > 0.99."""
        a = [1.0, 0.1] + [0.0] * 8
        b = [1.0, 0.11] + [0.0] * 8
        return a, b

    def test_consolidate_merges_near_identical_episodes(self):
        path = _temp_db()
        try:
            conn = sqlite3.connect(path)
            _full_schema(conn)
            va, vb = self._similar_vectors()
            _insert_episode(conn, observation="ep_a", vector=va,
                            confidence=0.6, feedback_weight=1.0)
            _insert_episode(conn, observation="ep_b", vector=vb,
                            confidence=0.5, feedback_weight=1.0)
            conn.close()

            eng = _make_engine(path)
            merged = eng._phase_consolidate()

            _c = sqlite3.connect(path)
            rows = _c.execute(
                "SELECT forgotten FROM episodic_memory ORDER BY id"
            ).fetchall()
            _c.close()
            forgotten_count = sum(r[0] for r in rows)
            assert merged >= 1
            assert forgotten_count >= 1
        finally:
            os.unlink(path)

    def test_consolidate_ignores_dissimilar_episodes(self):
        path = _temp_db()
        try:
            conn = sqlite3.connect(path)
            _full_schema(conn)
            va = [1.0, 0.0] + [0.0] * 8
            vb = [0.0, 1.0] + [0.0] * 8   # orthogonal — cosine = 0
            _insert_episode(conn, observation="ep_a", vector=va,
                            confidence=0.6, feedback_weight=1.0)
            _insert_episode(conn, observation="ep_b", vector=vb,
                            confidence=0.6, feedback_weight=1.0)
            conn.close()

            eng = _make_engine(path)
            merged = eng._phase_consolidate()

            assert merged == 0
        finally:
            os.unlink(path)

    def test_consolidate_empty_db_no_crash(self):
        path = _temp_db()
        try:
            conn = sqlite3.connect(path)
            _full_schema(conn)
            conn.close()
            eng = _make_engine(path)
            merged = eng._phase_consolidate()
            assert merged == 0
        finally:
            os.unlink(path)


# ─────────────────────────────────────────────────────────────────────
# run_full_cycle
# ─────────────────────────────────────────────────────────────────────

class TestRunFullCycle:

    def _build_db(self):
        path = _temp_db()
        conn = sqlite3.connect(path)
        _full_schema(conn)
        return path, conn

    def test_full_cycle_empty_db_no_crash(self):
        path, conn = self._build_db()
        conn.close()
        try:
            from cognia.consolidation_engine import ConsolidationEngine
            eng = ConsolidationEngine(db_path=path)
            result = eng.run_full_cycle()
            assert result is not None
        finally:
            _unlink_db(path)

    def test_full_cycle_returns_consolidation_result(self):
        from cognia.consolidation_engine import ConsolidationResult
        path, conn = self._build_db()
        conn.close()
        try:
            from cognia.consolidation_engine import ConsolidationEngine
            eng = ConsolidationEngine(db_path=path)
            result = eng.run_full_cycle()
            assert isinstance(result, ConsolidationResult)
        finally:
            _unlink_db(path)

    def test_full_cycle_result_has_expected_fields(self):
        path, conn = self._build_db()
        conn.close()
        try:
            from cognia.consolidation_engine import ConsolidationEngine
            eng = ConsolidationEngine(db_path=path)
            result = eng.run_full_cycle()
            assert hasattr(result, "purged")
            assert hasattr(result, "weakened")
            assert hasattr(result, "consolidated")
            assert hasattr(result, "reinforced")
            assert hasattr(result, "decayed")
            assert hasattr(result, "elapsed_ms")
            assert result.elapsed_ms >= 0
        finally:
            _unlink_db(path)

    def test_full_cycle_with_data_no_crash(self):
        path, conn = self._build_db()
        old_ts = _days_ago_iso(20)
        for i in range(5):
            _insert_episode(conn, observation=f"ep_{i}", confidence=0.5,
                            feedback_weight=1.0, timestamp=old_ts)
        conn.close()
        try:
            from cognia.consolidation_engine import ConsolidationEngine
            eng = ConsolidationEngine(db_path=path)
            result = eng.run_full_cycle()
            assert result is not None
        finally:
            _unlink_db(path)

    def test_full_cycle_cycle_type_is_full(self):
        path, conn = self._build_db()
        conn.close()
        try:
            from cognia.consolidation_engine import ConsolidationEngine
            eng = ConsolidationEngine(db_path=path)
            result = eng.run_full_cycle()
            assert result.cycle_type == "full"
        finally:
            _unlink_db(path)
