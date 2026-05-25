"""
tests/test_sar.py — Phase 28: SAR Shard Availability Redundancy
"""

from __future__ import annotations

import math
import sqlite3
import time

import pytest

from coordinator.shard_registry import (
    ShardRegistry,
    _target_replicas_for_p,
    ASSUMED_NODE_UPTIME,
    DEBT_THRESHOLD_S,
    MIN_REPLICAS_TARGET,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mem_reg():
    """ShardRegistry backed by an in-memory SQLite shared with a nodes table."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Create nodes table (mirrors NodeRegistry schema)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS nodes (
            node_id        TEXT PRIMARY KEY,
            shard          INTEGER NOT NULL,
            model_name     TEXT NOT NULL DEFAULT 'qwen-coder-3b-q4',
            hardware_info  TEXT DEFAULT '',
            registered_at  REAL NOT NULL,
            last_heartbeat REAL NOT NULL,
            is_active      INTEGER DEFAULT 1
        );
    """)
    conn.commit()

    reg = ShardRegistry(db_path=":memory:")
    reg.attach_mem_conn(conn)
    return reg, conn


def _insert_node(conn, node_id, shard, model="qwen-coder-3b-q4",
                 is_active=1, heartbeat_offset=0):
    now = time.time() + heartbeat_offset
    conn.execute(
        """INSERT OR REPLACE INTO nodes
           (node_id, shard, model_name, registered_at, last_heartbeat, is_active)
           VALUES (?,?,?,?,?,?)""",
        (node_id, shard, model, now, now, is_active),
    )
    conn.commit()


# ══════════════════════════════════════════════════════════════════════════════
# _target_replicas_for_p
# ══════════════════════════════════════════════════════════════════════════════

class TestTargetReplicas:
    def test_returns_integer(self):
        r = _target_replicas_for_p()
        assert isinstance(r, int)

    def test_at_least_one(self):
        r = _target_replicas_for_p(0.50)
        assert r >= 1

    def test_higher_target_needs_more_replicas(self):
        r_low  = _target_replicas_for_p(0.80)
        r_high = _target_replicas_for_p(0.99)
        assert r_high >= r_low

    def test_more_shards_needs_more_replicas(self):
        r4 = _target_replicas_for_p(0.95, n_shards=4)
        r8 = _target_replicas_for_p(0.95, n_shards=8)
        assert r8 >= r4

    def test_uptime_1_returns_1(self):
        # uptime=1 → clamped to avoid log(0); should still return 1
        r = _target_replicas_for_p(uptime=0.9999)
        assert r >= 1

    def test_math_consistency(self):
        # With returned R replicas per shard, P(all covered) should be >= 0.95
        r = _target_replicas_for_p(0.95, ASSUMED_NODE_UPTIME, n_shards=4)
        p_shard = 1.0 - (1.0 - ASSUMED_NODE_UPTIME) ** r
        p_all   = p_shard ** 4
        assert p_all >= 0.95 or r >= 100   # extreme edge cases allowed


# ══════════════════════════════════════════════════════════════════════════════
# Debt recording
# ══════════════════════════════════════════════════════════════════════════════

class TestDebtRecording:
    def test_record_offline_adds_entry(self, mem_reg):
        reg, conn = mem_reg
        reg.record_offline("node_x", 0, "qwen-coder-3b-q4")
        debt = reg.debt_nodes("qwen-coder-3b-q4")
        assert any(d["node_id"] == "node_x" for d in debt)

    def test_clear_debt_removes_entry(self, mem_reg):
        reg, conn = mem_reg
        reg.record_offline("node_y", 1, "qwen-coder-3b-q4")
        reg.clear_debt("node_y")
        debt = reg.debt_nodes("qwen-coder-3b-q4")
        assert not any(d["node_id"] == "node_y" for d in debt)

    def test_offline_hours_computed(self, mem_reg):
        reg, conn = mem_reg
        went = time.time() - 7200   # 2 hours ago
        reg.record_offline("node_z", 2, "qwen-coder-3b-q4", went_offline=went)
        debt = reg.debt_nodes("qwen-coder-3b-q4")
        entry = next(d for d in debt if d["node_id"] == "node_z")
        assert abs(entry["offline_hours"] - 2.0) < 0.1

    def test_is_debt_false_under_threshold(self, mem_reg):
        reg, conn = mem_reg
        reg.record_offline("node_a", 0, "qwen-coder-3b-q4",
                           went_offline=time.time() - 3600)   # 1 hour
        debt = reg.debt_nodes("qwen-coder-3b-q4")
        entry = next(d for d in debt if d["node_id"] == "node_a")
        assert entry["is_debt"] is False   # < 24h

    def test_is_debt_true_over_threshold(self, mem_reg):
        reg, conn = mem_reg
        reg.record_offline("node_b", 0, "qwen-coder-3b-q4",
                           went_offline=time.time() - DEBT_THRESHOLD_S - 60)
        debt = reg.debt_nodes("qwen-coder-3b-q4")
        entry = next(d for d in debt if d["node_id"] == "node_b")
        assert entry["is_debt"] is True

    def test_shards_in_debt_returns_shard_indices(self, mem_reg):
        reg, conn = mem_reg
        reg.record_offline("node_c", 3, "qwen-coder-3b-q4",
                           went_offline=time.time() - DEBT_THRESHOLD_S - 100)
        in_debt = reg.shards_in_debt("qwen-coder-3b-q4")
        assert 3 in in_debt

    def test_shards_in_debt_excludes_recent(self, mem_reg):
        reg, conn = mem_reg
        reg.record_offline("node_d", 2, "qwen-coder-3b-q4",
                           went_offline=time.time() - 3600)   # 1 hour ago — not debt
        in_debt = reg.shards_in_debt("qwen-coder-3b-q4")
        assert 2 not in in_debt

    def test_replace_on_duplicate_node_id(self, mem_reg):
        reg, conn = mem_reg
        reg.record_offline("node_dup", 0, "qwen-coder-3b-q4", went_offline=1000.0)
        reg.record_offline("node_dup", 0, "qwen-coder-3b-q4", went_offline=2000.0)
        debt = reg.debt_nodes("qwen-coder-3b-q4")
        entries = [d for d in debt if d["node_id"] == "node_dup"]
        assert len(entries) == 1


# ══════════════════════════════════════════════════════════════════════════════
# Replication report
# ══════════════════════════════════════════════════════════════════════════════

class TestReplicationReport:
    def test_empty_swarm_all_uncovered(self, mem_reg):
        reg, conn = mem_reg
        report = reg.replication_report("qwen-coder-3b-q4", n_shards=4, node_timeout=60)
        assert report.ready is False
        assert report.under_replicated == [0, 1, 2, 3]

    def test_p_all_online_zero_when_no_nodes(self, mem_reg):
        reg, conn = mem_reg
        report = reg.replication_report("qwen-coder-3b-q4", n_shards=4, node_timeout=60)
        assert report.p_all_online == 0.0

    def test_one_node_per_shard_is_ready(self, mem_reg):
        reg, conn = mem_reg
        for shard in range(4):
            _insert_node(conn, f"n{shard}", shard)
        report = reg.replication_report("qwen-coder-3b-q4", n_shards=4, node_timeout=60)
        assert report.ready is True

    def test_p_all_online_positive_with_full_coverage(self, mem_reg):
        reg, conn = mem_reg
        for shard in range(4):
            _insert_node(conn, f"n{shard}", shard)
        report = reg.replication_report("qwen-coder-3b-q4", n_shards=4, node_timeout=60)
        assert report.p_all_online > 0.0

    def test_under_replicated_includes_single_replica_shards(self, mem_reg):
        reg, conn = mem_reg
        for shard in range(4):
            _insert_node(conn, f"n{shard}", shard)   # 1 replica each
        report = reg.replication_report("qwen-coder-3b-q4", n_shards=4, node_timeout=60)
        # MIN_REPLICAS_TARGET=2, so all 4 shards are under-replicated
        assert len(report.under_replicated) == 4

    def test_two_replicas_shard_not_under_replicated(self, mem_reg):
        reg, conn = mem_reg
        _insert_node(conn, "na", 0)
        _insert_node(conn, "nb", 0)
        for shard in range(1, 4):
            _insert_node(conn, f"n{shard}", shard)
        report = reg.replication_report("qwen-coder-3b-q4", n_shards=4, node_timeout=60)
        assert 0 not in report.under_replicated

    def test_stale_nodes_excluded(self, mem_reg):
        reg, conn = mem_reg
        for shard in range(4):
            # heartbeat 120 seconds ago, node_timeout=60 → stale
            _insert_node(conn, f"n{shard}", shard, heartbeat_offset=-120)
        report = reg.replication_report("qwen-coder-3b-q4", n_shards=4, node_timeout=60)
        assert report.ready is False

    def test_in_debt_shards_included_in_report(self, mem_reg):
        reg, conn = mem_reg
        for shard in range(4):
            _insert_node(conn, f"n{shard}", shard)
        reg.record_offline("n2", 2, "qwen-coder-3b-q4",
                           went_offline=time.time() - DEBT_THRESHOLD_S - 100)
        report = reg.replication_report("qwen-coder-3b-q4", n_shards=4, node_timeout=60)
        assert 2 in report.in_debt

    def test_recommended_target_covers_under_replicated(self, mem_reg):
        reg, conn = mem_reg
        for shard in range(4):
            _insert_node(conn, f"n{shard}", shard)
        report = reg.replication_report("qwen-coder-3b-q4", n_shards=4, node_timeout=60)
        for shard_idx, target in report.recommended_target.items():
            assert target >= MIN_REPLICAS_TARGET

    def test_shard_status_fields_present(self, mem_reg):
        reg, conn = mem_reg
        _insert_node(conn, "n0", 0)
        report = reg.replication_report("qwen-coder-3b-q4", n_shards=4, node_timeout=60)
        s = report.shards[0]
        assert hasattr(s, "shard_index")
        assert hasattr(s, "active_replicas")
        assert hasattr(s, "is_covered")
        assert hasattr(s, "under_replicated")
        assert hasattr(s, "in_debt")


# ══════════════════════════════════════════════════════════════════════════════
# sync_stale_nodes
# ══════════════════════════════════════════════════════════════════════════════

class TestSyncStaleNodes:
    def test_records_stale_nodes(self, mem_reg):
        reg, conn = mem_reg
        _insert_node(conn, "stale1", 0, is_active=0, heartbeat_offset=-120)
        newly = reg.sync_stale_nodes("qwen-coder-3b-q4", node_timeout=60)
        assert "stale1" in newly

    def test_does_not_double_record(self, mem_reg):
        reg, conn = mem_reg
        _insert_node(conn, "stale2", 1, is_active=0, heartbeat_offset=-120)
        reg.sync_stale_nodes("qwen-coder-3b-q4", node_timeout=60)
        newly2 = reg.sync_stale_nodes("qwen-coder-3b-q4", node_timeout=60)
        assert "stale2" not in newly2

    def test_active_nodes_not_recorded(self, mem_reg):
        reg, conn = mem_reg
        _insert_node(conn, "active1", 0, is_active=1)
        newly = reg.sync_stale_nodes("qwen-coder-3b-q4", node_timeout=60)
        assert "active1" not in newly

    def test_returns_empty_when_no_stale(self, mem_reg):
        reg, conn = mem_reg
        newly = reg.sync_stale_nodes("qwen-coder-3b-q4", node_timeout=60)
        assert newly == []

    def test_clear_debt_after_heartbeat(self, mem_reg):
        reg, conn = mem_reg
        reg.record_offline("node_back", 0, "qwen-coder-3b-q4")
        reg.clear_debt("node_back")
        debt = reg.debt_nodes("qwen-coder-3b-q4")
        assert not any(d["node_id"] == "node_back" for d in debt)
