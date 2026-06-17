"""
tests/test_db_pool_migration_v3.py
==================================
Closing regression for FASE 0b (db_pool migration of the cognia_v3 package).

1. SCAN test: fails if a direct `sqlite3.connect(` reappears anywhere under
   cognia_v3/ — the repo's hard rule is "sin sqlite3.connect() directo -> usar
   storage/db_pool.py". db_pool is the ONLY sanctioned place to open a raw
   connection, and it lives in storage/, not cognia_v3/.

2. Smoke tests: instantiate the migrated class-based modules on a temp DB.
   Construction runs their schema init (executescript / CREATE TABLE) THROUGH the
   pool, and we assert (a) the pool registered an entry for the path and (b) the
   tables were actually created — proving the pooled connection path works.
"""

import os
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from storage.db_pool import pool_stats, close_pool

CV3 = ROOT / "cognia_v3"


# ─────────────────────────────────────────────────────────────────────
# 1. SCAN — no direct sqlite3.connect( anywhere in cognia_v3
# ─────────────────────────────────────────────────────────────────────

def test_no_direct_sqlite3_connect_in_cognia_v3():
    offenders = []
    for py in CV3.rglob("*.py"):
        text = py.read_text(encoding="utf-8", errors="replace")
        if "sqlite3.connect(" in text:
            # report the offending line numbers for a useful failure message
            for i, line in enumerate(text.splitlines(), 1):
                if "sqlite3.connect(" in line:
                    offenders.append(f"{py.relative_to(ROOT)}:{i}: {line.strip()}")
    assert not offenders, (
        "Direct sqlite3.connect( found in cognia_v3 (use storage/db_pool):\n"
        + "\n".join(offenders)
    )


# ─────────────────────────────────────────────────────────────────────
# 2. Smoke — pooled schema init for the migrated class-based modules
# ─────────────────────────────────────────────────────────────────────

def _tables(path):
    c = sqlite3.connect(path)
    names = {r[0] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    c.close()
    return names


def _unlink(path):
    try:
        _c = sqlite3.connect(path)
        _c.execute("PRAGMA wal_checkpoint(FULL)")
        _c.execute("PRAGMA journal_mode=DELETE")
        _c.close()
    except Exception:
        pass
    for s in ("", "-wal", "-shm"):
        try:
            os.unlink(path + s)
        except FileNotFoundError:
            pass


@pytest.fixture()
def tmp_db(tmp_path):
    path = str(tmp_path / "mig.db")
    yield path
    close_pool(path)
    _unlink(path)


def _pool_engaged(path):
    return any(path in k for k in pool_stats())


def test_prompt_metrics_store_pooled_init(tmp_db):
    from cognia_v3.interfaces.prompt_optimizer import PromptMetricsStore
    PromptMetricsStore(db_path=tmp_db)        # __init__ -> _init_table via pool
    assert _pool_engaged(tmp_db)
    assert _tables(tmp_db)                     # at least one table created


def test_model_collapse_guard_pooled_init(tmp_db):
    from cognia_v3.core.model_collapse_guard import ModelCollapseGuard
    ModelCollapseGuard(db_path=tmp_db)         # __init__ -> _init_db via pool
    assert _pool_engaged(tmp_db)
    assert _tables(tmp_db)


def test_feedback_engine_pooled_init(tmp_db):
    # _init_schema runs ALTER TABLE episodic_memory (additive migration that, like
    # production, assumes the base table exists), then CREATE TABLE feedback_log.
    _c = sqlite3.connect(tmp_db)
    _c.execute("CREATE TABLE episodic_memory (id INTEGER PRIMARY KEY, importance REAL)")
    _c.commit()
    _c.close()
    from cognia_v3.core.feedback_engine import FeedbackEngine
    FeedbackEngine(db_path=tmp_db)             # __init__ -> _init_schema via pool
    assert _pool_engaged(tmp_db)
    assert "feedback_log" in _tables(tmp_db)   # created through the pooled connection
