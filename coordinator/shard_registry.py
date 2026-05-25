"""
coordinator/shard_registry.py
==============================
SAR — Shard Availability Redundancy.

Wraps NodeRegistry to add per-shard replication tracking, under-replication
detection, and shard-debt marking for nodes that go offline with a unique shard.

Three-layer design:
  1. Replication tracking:  per-shard replica count in the DB nodes table.
  2. Shard debt:            nodes inactive > DEBT_THRESHOLD_S with a unique
                            shard are flagged; the coordinator urgently recruits
                            new nodes for those shards.
  3. Availability estimate: p_all_online = product of P(shard_i has >= 1 node up)
                            Exposed in status so operators see real coverage odds.

The warm pool (~2 GB coordinator-side cache) is FUERA DE ALCANCE for Railway
deployments (RAM limit). Debt + recruitment handles the same failure mode with
zero coordinator memory overhead.
"""

from __future__ import annotations

import math
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

# ── Constants ─────────────────────────────────────────────────────────────────

# Node uptime fraction assumed per-shard when no empirical data is available.
ASSUMED_NODE_UPTIME = 0.50

# Hours of continuous offline time before a shard is flagged as under_replicated
# and the coordinator actively recruits a replacement.
DEBT_THRESHOLD_S = 24 * 3600     # 24 hours

# Target minimum replica count per shard.
MIN_REPLICAS_TARGET = 2


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class ShardStatus:
    shard_index:     int
    active_replicas: int
    is_covered:      bool   # at least 1 active node
    under_replicated: bool  # active_replicas < MIN_REPLICAS_TARGET
    in_debt:         bool   # any node has been offline > DEBT_THRESHOLD_S with this shard


@dataclass
class ReplicationReport:
    model_name:          str
    n_shards:            int
    shards:              List[ShardStatus]
    p_all_online:        float    # probability all shards have >= 1 node active
    ready:               bool     # all shards covered
    under_replicated:    List[int]  # shard indices needing more nodes
    in_debt:             List[int]  # shard indices with debt nodes
    recommended_target:  Dict[int, int]  # {shard: target_replicas} to reach 95% p_all


def _target_replicas_for_p(p_target: float = 0.95,
                            uptime: float = ASSUMED_NODE_UPTIME,
                            n_shards: int = 4) -> int:
    """
    Minimum replicas R per shard so that P(at least 1 node up per shard) >= p_target.

    P(shard covered) = 1 - (1 - uptime)^R
    P(all covered)   = P(shard covered)^n_shards >= p_target
    => P(shard covered) >= p_target^(1/n_shards)
    => R >= log(1 - p_target^(1/n_shards)) / log(1 - uptime)
    """
    if uptime <= 0 or uptime >= 1:
        return 1
    p_shard = p_target ** (1.0 / max(1, n_shards))
    if p_shard >= 1.0:
        return 1
    r = math.log(1.0 - p_shard) / math.log(1.0 - uptime)
    return max(1, math.ceil(r))


# ── ShardRegistry ─────────────────────────────────────────────────────────────

class ShardRegistry:
    """
    Thin layer on top of NodeRegistry's SQLite DB.

    Does NOT own a DB connection — reads from the same file via its own
    read-only queries.  Writes are limited to the shard_debt table it owns.
    """

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS shard_debt (
        node_id        TEXT NOT NULL,
        shard_index    INTEGER NOT NULL,
        model_name     TEXT NOT NULL,
        went_offline   REAL NOT NULL,
        PRIMARY KEY (node_id, model_name)
    );
    CREATE INDEX IF NOT EXISTS idx_debt_shard ON shard_debt(shard_index, model_name);
    """

    def __init__(self, db_path: str = "coordinator.db"):
        self.db_path = db_path
        self._mem_conn: Optional[sqlite3.Connection] = None
        if db_path == ":memory:":
            # For tests: share a connection with NodeRegistry caller.
            # Caller must call attach_mem_conn() before use.
            self._mem_conn = None
        self._init_schema()

    def attach_mem_conn(self, conn: sqlite3.Connection) -> None:
        """Share an in-memory connection (used in tests alongside NodeRegistry)."""
        self._mem_conn = conn
        self._mem_conn.row_factory = sqlite3.Row
        conn.executescript(self._SCHEMA)
        conn.commit()

    @contextmanager
    def _conn(self):
        if self._mem_conn is not None:
            yield self._mem_conn
            self._mem_conn.commit()
        else:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

    def _init_schema(self):
        if self._mem_conn is not None:
            return   # deferred — caller calls attach_mem_conn()
        with self._conn() as c:
            c.executescript(self._SCHEMA)

    # ── Debt tracking ─────────────────────────────────────────────────────────

    def record_offline(self, node_id: str, shard_index: int,
                       model_name: str, went_offline: Optional[float] = None) -> None:
        """
        Record that a node went offline.  Call this when heartbeat expires.
        went_offline defaults to now.
        """
        ts = went_offline if went_offline is not None else time.time()
        with self._conn() as c:
            c.execute(
                """INSERT OR REPLACE INTO shard_debt
                   (node_id, shard_index, model_name, went_offline)
                   VALUES (?,?,?,?)""",
                (node_id, shard_index, model_name, ts),
            )

    def clear_debt(self, node_id: str) -> None:
        """Remove debt entry when a node comes back online."""
        with self._conn() as c:
            c.execute("DELETE FROM shard_debt WHERE node_id=?", (node_id,))

    def shards_in_debt(self, model_name: str) -> List[int]:
        """Shard indices where any node has been offline > DEBT_THRESHOLD_S."""
        cutoff = time.time() - DEBT_THRESHOLD_S
        with self._conn() as c:
            rows = c.execute(
                """SELECT DISTINCT shard_index FROM shard_debt
                   WHERE model_name=? AND went_offline < ?""",
                (model_name, cutoff),
            ).fetchall()
        return [r["shard_index"] for r in rows]

    def debt_nodes(self, model_name: str) -> List[dict]:
        """All debt entries (any age) for a given model."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT node_id, shard_index, went_offline FROM shard_debt WHERE model_name=?",
                (model_name,),
            ).fetchall()
        now = time.time()
        return [
            {
                "node_id":      r["node_id"],
                "shard_index":  r["shard_index"],
                "offline_hours": round((now - r["went_offline"]) / 3600, 1),
                "is_debt":      (now - r["went_offline"]) >= DEBT_THRESHOLD_S,
            }
            for r in rows
        ]

    # ── Replication report ────────────────────────────────────────────────────

    def replication_report(self, model_name: str = "qwen-coder-3b-q4",
                            n_shards: int = 4,
                            node_timeout: float = 60.0) -> ReplicationReport:
        """
        Build a full replication report from the live nodes table.

        node_timeout: seconds without heartbeat before a node is considered inactive
                      (mirrors NodeRegistry.NODE_TIMEOUT).
        """
        cutoff      = time.time() - node_timeout
        debt_shards = set(self.shards_in_debt(model_name))

        with self._conn() as c:
            rows = c.execute(
                """SELECT shard, COUNT(*) as cnt
                   FROM nodes
                   WHERE is_active=1 AND model_name=? AND last_heartbeat >= ?
                   GROUP BY shard""",
                (model_name, cutoff),
            ).fetchall()

        replica_counts: Dict[int, int] = {i: 0 for i in range(n_shards)}
        for row in rows:
            replica_counts[row["shard"]] = row["cnt"]

        target_r = _target_replicas_for_p(0.95, ASSUMED_NODE_UPTIME, n_shards)

        statuses: List[ShardStatus] = []
        under_rep: List[int] = []
        in_debt: List[int] = []

        for idx in range(n_shards):
            cnt        = replica_counts[idx]
            covered    = cnt > 0
            under      = cnt < MIN_REPLICAS_TARGET
            debt       = idx in debt_shards
            statuses.append(ShardStatus(
                shard_index      = idx,
                active_replicas  = cnt,
                is_covered       = covered,
                under_replicated = under,
                in_debt          = debt,
            ))
            if under:
                under_rep.append(idx)
            if debt:
                in_debt.append(idx)

        # P(all shards covered) = product of P(shard_i has >= 1 active node)
        # We use empirical coverage as P(covered) when we have data.
        p_all = 1.0
        for s in statuses:
            if s.active_replicas == 0:
                # Assume ASSUMED_NODE_UPTIME as marginal P for offline shard
                p_shard = 0.0
            else:
                p_down = (1.0 - ASSUMED_NODE_UPTIME) ** s.active_replicas
                p_shard = 1.0 - p_down
            p_all *= p_shard

        recommended = {
            i: target_r
            for i, s in enumerate(statuses)
            if s.active_replicas < target_r
        }

        return ReplicationReport(
            model_name        = model_name,
            n_shards          = n_shards,
            shards            = statuses,
            p_all_online      = round(p_all, 4),
            ready             = all(s.is_covered for s in statuses),
            under_replicated  = under_rep,
            in_debt           = in_debt,
            recommended_target= recommended,
        )

    # ── Convenience: sync debt from NodeRegistry stale scan ───────────────────

    def sync_stale_nodes(self, model_name: str,
                         node_timeout: float = 60.0) -> List[str]:
        """
        Scan the nodes table for newly-stale nodes (heartbeat expired but not yet
        in shard_debt) and record them.  Returns list of node_ids newly recorded.

        Call this from the coordinator's periodic cleanup task.
        """
        cutoff = time.time() - node_timeout
        with self._conn() as c:
            stale = c.execute(
                """SELECT node_id, shard, model_name, last_heartbeat
                   FROM nodes
                   WHERE is_active=0 AND model_name=? AND last_heartbeat < ?""",
                (model_name, cutoff),
            ).fetchall()

            existing_debt = {
                r["node_id"]
                for r in c.execute(
                    "SELECT node_id FROM shard_debt WHERE model_name=?", (model_name,)
                ).fetchall()
            }

        newly_recorded = []
        for row in stale:
            if row["node_id"] not in existing_debt:
                self.record_offline(
                    node_id     = row["node_id"],
                    shard_index = row["shard"],
                    model_name  = row["model_name"],
                    went_offline= row["last_heartbeat"],
                )
                newly_recorded.append(row["node_id"])

        return newly_recorded
