"""
Tests for the configurable memory cap (cognia/memory/memory_budget.py).

Pins both axes (count + disk MB), the lowest-value-first purge order, the
no-op-when-under-limit case, and that the disk cap actually shrinks the file.
"""

import json
import os

import pytest

from cognia.database import init_db
from storage.db_pool import db_connect_pooled, close_pool
from cognia.memory import memory_budget as MB

_VEC = json.dumps([0.123] * 384)


@pytest.fixture
def db(tmp_path):
    p = str(tmp_path / "mem.db")
    init_db(p)
    yield p
    close_pool(p)  # release the file so Windows can clean tmp_path


def _insert(db_path, n, *, bad_first=0, pad=""):
    conn = db_connect_pooled(db_path)
    try:
        for i in range(n):
            bad = i < bad_first
            conn.execute(
                "INSERT INTO episodic_memory (timestamp, observation, vector, "
                "confidence, importance, feedback_weight, access_count, forgotten) "
                "VALUES (?,?,?,?,?,?,?,0)",
                ("2026-01-01", f"memoria {i} {pad}", _VEC,
                 0.3 if bad else 0.8, 0.5 if bad else 1.5,
                 0.2 if bad else 1.5, 0 if bad else 10),
            )
        conn.commit()
    finally:
        conn.close()


def test_get_limits_reads_env(monkeypatch):
    monkeypatch.setenv("COGNIA_MAX_MEMORIES", "1000")
    monkeypatch.setenv("COGNIA_MAX_DB_MB", "50")
    assert MB.get_limits() == (1000, 50)


def test_get_limits_unset_is_none(monkeypatch):
    monkeypatch.delenv("COGNIA_MAX_MEMORIES", raising=False)
    monkeypatch.delenv("COGNIA_MAX_DB_MB", raising=False)
    assert MB.get_limits() == (None, None)


def test_current_usage(db):
    _insert(db, 10)
    u = MB.current_usage(db)
    assert u["active"] == 10 and u["total"] == 10 and u["mb"] > 0


def test_count_cap_soft_deletes_worst_first(db):
    _insert(db, 100, bad_first=30)  # first 30 are low-value
    rep = MB.enforce_memory_budget(db, max_count=70, max_mb=None)
    assert rep["soft_deleted"] == 30
    assert MB.current_usage(db)["active"] == 70
    # The low-value (feedback_weight=0.2) ones are the ones forgotten.
    conn = db_connect_pooled(db)
    try:
        bad_active = conn.execute(
            "SELECT COUNT(*) FROM episodic_memory WHERE forgotten=0 AND feedback_weight=0.2"
        ).fetchone()[0]
    finally:
        conn.close()
    assert bad_active == 0


def test_no_op_when_under_limits(db):
    _insert(db, 20)
    rep = MB.enforce_memory_budget(db, max_count=1000, max_mb=1000)
    assert not rep["enforced"]
    assert rep["soft_deleted"] == 0 and rep["hard_deleted"] == 0
    assert MB.current_usage(db)["active"] == 20


def test_disk_cap_hard_deletes_and_shrinks(db):
    _insert(db, 600, pad="x" * 80)
    before = MB.current_usage(db)
    assert before["mb"] > 1.0  # ensure we're over the cap we set
    rep = MB.enforce_memory_budget(db, max_count=None, max_mb=1.0)
    after = MB.current_usage(db)
    assert rep["hard_deleted"] > 0
    assert after["mb"] < before["mb"]      # file actually shrank (VACUUM)
    assert after["mb"] <= 1.3              # near the cap (tolerance for granularity)


def test_disk_cap_keeps_a_floor(db):
    # A tiny cap must not empty the store; a floor of rows survives.
    _insert(db, 200, pad="y" * 80)
    MB.enforce_memory_budget(db, max_count=None, max_mb=0.01)
    assert MB.current_usage(db)["total"] >= 50
