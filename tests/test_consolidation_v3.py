"""
tests/test_consolidation_v3.py
==============================
Direct test suite for the PRODUCTION consolidation engine:
    cognia_v3.memory.consolidation_engine

IMPORTANT (verified 2026-06-16): production (cognia/cognia.py:317) imports the
consolidation engine from ``cognia_v3.memory.consolidation_engine``. The older
suite ``tests/test_consolidation.py`` imports ``cognia.consolidation_engine``,
which is a DIVERGED twin (numpy BLAS consolidate, dynamic decay) that production
does NOT use. So the prod engine had zero direct coverage. This file covers it.

The teardown closes the db_pool BEFORE unlinking the temp file so the migration
to ``storage/db_pool`` (which keeps 5 eager connections open per path) does not
block file deletion on Windows. It is correct both before and after that
migration (close_pool is a harmless no-op when the module still uses a direct
connection that is not registered in the pool).
"""

import json
import os
import sqlite3
import sys
import tempfile
import threading
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cognia_v3.memory import consolidation_engine as ce
from storage.db_pool import close_pool


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

def _full_schema(conn):
    """Create the complete episodic_memory + semantic_memory schema."""
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
    conn.commit()


def _unlink_db(path: str) -> None:
    """Delete a SQLite DB and its WAL/SHM files safely on Windows."""
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
                    timestamp=None, forgotten=0, emotion_score=0.0):
    if vector is None:
        vector = [0.1] * 10
    ts = timestamp or datetime.now().isoformat()
    conn.execute("""
        INSERT INTO episodic_memory
        (timestamp, observation, label, vector, confidence, importance,
         feedback_weight, access_count, last_access, forgotten, emotion_score)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (ts, observation, label, json.dumps(vector),
          confidence, importance, feedback_weight, access_count, ts,
          forgotten, emotion_score))
    conn.commit()
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def _insert_concept(conn, *, concept, vector, confidence=0.5, support=1,
                    associations="{}"):
    conn.execute("""
        INSERT INTO semantic_memory (concept, confidence, support, vector, associations)
        VALUES (?, ?, ?, ?, ?)
    """, (concept, confidence, support, json.dumps(vector), associations))
    conn.commit()


@pytest.fixture()
def db():
    """Temp DB path with full schema; closes the pool before unlink (Windows-safe)."""
    tf = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tf.close()
    path = tf.name
    conn = sqlite3.connect(path)
    _full_schema(conn)
    conn.close()
    yield path
    close_pool(path)      # drain pooled handles (post-migration) so unlink succeeds
    _unlink_db(path)


def _engine(path):
    """Build a fresh engine (NOT the module singleton) bound to this db."""
    return ce.ConsolidationEngine(db_path=path)


# ─────────────────────────────────────────────────────────────────────
# _phase_purge
# ─────────────────────────────────────────────────────────────────────

class TestPhasePurge:

    def test_purge_marks_low_quality_episode_forgotten(self, db):
        old_ts = _days_ago_iso(10)
        eng = _engine(db)
        conn = sqlite3.connect(db)
        ep_id = _insert_episode(conn, observation="bad", confidence=0.25,
                                feedback_weight=0.20, access_count=0,
                                timestamp=old_ts, label="other")
        conn.close()

        purged = eng._phase_purge()

        _c = sqlite3.connect(db)
        forgotten = _c.execute(
            "SELECT forgotten FROM episodic_memory WHERE id=?", (ep_id,)
        ).fetchone()[0]
        _c.close()
        assert purged >= 1
        assert forgotten == 1

    def test_purge_spares_recent(self, db):
        eng = _engine(db)
        conn = sqlite3.connect(db)
        ep_id = _insert_episode(conn, confidence=0.25, feedback_weight=0.20,
                                access_count=0, timestamp=datetime.now().isoformat(),
                                label="other")
        conn.close()

        purged = eng._phase_purge()

        _c = sqlite3.connect(db)
        forgotten = _c.execute(
            "SELECT forgotten FROM episodic_memory WHERE id=?", (ep_id,)
        ).fetchone()[0]
        _c.close()
        assert purged == 0
        assert forgotten == 0

    def test_purge_spares_protected_label(self, db):
        old_ts = _days_ago_iso(10)
        eng = _engine(db)
        conn = sqlite3.connect(db)
        ep_id = _insert_episode(conn, confidence=0.25, feedback_weight=0.20,
                                access_count=0, timestamp=old_ts, label="feedback")
        conn.close()

        eng._phase_purge()

        _c = sqlite3.connect(db)
        forgotten = _c.execute(
            "SELECT forgotten FROM episodic_memory WHERE id=?", (ep_id,)
        ).fetchone()[0]
        _c.close()
        assert forgotten == 0


# ─────────────────────────────────────────────────────────────────────
# _phase_weaken
# ─────────────────────────────────────────────────────────────────────

class TestPhaseWeaken:

    def test_weaken_reduces_importance(self, db):
        eng = _engine(db)
        conn = sqlite3.connect(db)
        _insert_episode(conn, importance=1.5, feedback_weight=0.40, confidence=0.5)
        conn.close()

        weakened = eng._phase_weaken()

        _c = sqlite3.connect(db)
        imp = _c.execute("SELECT importance FROM episodic_memory").fetchone()[0]
        _c.close()
        assert weakened >= 1
        assert imp < 1.5

    def test_weaken_skips_high_weight(self, db):
        eng = _engine(db)
        conn = sqlite3.connect(db)
        _insert_episode(conn, importance=1.5, feedback_weight=1.0)
        conn.close()
        assert eng._phase_weaken() == 0


# ─────────────────────────────────────────────────────────────────────
# _phase_consolidate
# ─────────────────────────────────────────────────────────────────────

class TestPhaseConsolidate:

    def test_merges_near_identical(self, db):
        eng = _engine(db)
        va = [1.0, 0.10] + [0.0] * 8
        vb = [1.0, 0.11] + [0.0] * 8
        conn = sqlite3.connect(db)
        _insert_episode(conn, observation="a", vector=va, confidence=0.6,
                        feedback_weight=1.0)
        _insert_episode(conn, observation="b", vector=vb, confidence=0.5,
                        feedback_weight=1.0)
        conn.close()

        merged = eng._phase_consolidate()

        _c = sqlite3.connect(db)
        forgotten_count = sum(
            r[0] for r in _c.execute("SELECT forgotten FROM episodic_memory").fetchall()
        )
        _c.close()
        assert merged >= 1
        assert forgotten_count >= 1

    def test_ignores_orthogonal(self, db):
        eng = _engine(db)
        va = [1.0, 0.0] + [0.0] * 8
        vb = [0.0, 1.0] + [0.0] * 8
        conn = sqlite3.connect(db)
        _insert_episode(conn, observation="a", vector=va, confidence=0.6)
        _insert_episode(conn, observation="b", vector=vb, confidence=0.6)
        conn.close()
        assert eng._phase_consolidate() == 0


# ─────────────────────────────────────────────────────────────────────
# _phase_reinforce / _phase_decay / _phase_semantic_dedup
# ─────────────────────────────────────────────────────────────────────

class TestOtherPhases:

    def test_reinforce_boosts_confidence(self, db):
        eng = _engine(db)
        conn = sqlite3.connect(db)
        ep_id = _insert_episode(conn, confidence=0.5, feedback_weight=1.5,
                                access_count=10)
        conn.close()

        reinforced = eng._phase_reinforce()

        _c = sqlite3.connect(db)
        conf = _c.execute(
            "SELECT confidence FROM episodic_memory WHERE id=?", (ep_id,)
        ).fetchone()[0]
        _c.close()
        assert reinforced >= 1
        assert conf > 0.5

    def test_decay_reduces_importance_of_stale(self, db):
        eng = _engine(db)
        old_ts = _days_ago_iso(30)
        conn = sqlite3.connect(db)
        ep_id = _insert_episode(conn, importance=1.5, timestamp=old_ts,
                                access_count=0)
        conn.close()

        decayed = eng._phase_decay()

        _c = sqlite3.connect(db)
        imp = _c.execute(
            "SELECT importance FROM episodic_memory WHERE id=?", (ep_id,)
        ).fetchone()[0]
        _c.close()
        assert decayed >= 1
        assert imp < 1.5

    def test_semantic_dedup_removes_low_support_duplicate(self, db):
        eng = _engine(db)
        v = [1.0, 0.0] + [0.0] * 8
        conn = sqlite3.connect(db)
        _insert_concept(conn, concept="winner", vector=v, support=5)
        _insert_concept(conn, concept="loser",  vector=v, support=1)
        conn.close()

        removed = eng._phase_semantic_dedup()

        _c = sqlite3.connect(db)
        concepts = {r[0] for r in _c.execute("SELECT concept FROM semantic_memory").fetchall()}
        _c.close()
        assert removed >= 1
        assert "winner" in concepts
        assert "loser" not in concepts


# ─────────────────────────────────────────────────────────────────────
# run_full_cycle / stats
# ─────────────────────────────────────────────────────────────────────

class TestRunFullCycle:

    def test_empty_db_no_crash(self, db):
        result = _engine(db).run_full_cycle()
        assert result is not None
        assert result.cycle_type == "full"

    def test_result_has_expected_fields(self, db):
        result = _engine(db).run_full_cycle()
        for attr in ("purged", "weakened", "consolidated", "reinforced",
                     "decayed", "sem_deduped", "elapsed_ms"):
            assert hasattr(result, attr)
        assert result.elapsed_ms >= 0

    def test_with_data_runs_and_logs_cycle(self, db):
        old_ts = _days_ago_iso(20)
        conn = sqlite3.connect(db)
        for i in range(5):
            _insert_episode(conn, observation=f"ep_{i}", confidence=0.5,
                            feedback_weight=1.0, timestamp=old_ts)
        conn.close()

        eng = _engine(db)
        eng.run_full_cycle()

        _c = sqlite3.connect(db)
        cycles = _c.execute("SELECT COUNT(*) FROM consolidation_log").fetchone()[0]
        _c.close()
        assert cycles >= 1

    def test_stats_returns_dict(self, db):
        conn = sqlite3.connect(db)
        _insert_episode(conn, confidence=0.5, feedback_weight=1.0)
        conn.close()
        stats = _engine(db).stats()
        assert isinstance(stats, dict)
        assert stats.get("ep_total", 0) >= 1
