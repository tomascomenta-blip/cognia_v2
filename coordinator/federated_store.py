"""
coordinator/federated_store.py
==============================
FedAvg aggregation store for Cognia's federated learning layer.

Each node contributes a LoRA adapter (k_A, k_B, v_A, v_B) trained locally
during the sleep cycle. The coordinator aggregates them with weighted FedAvg
(weight = contributor tier's min_params_b) and serves the global adapter back.

Privacy: clients add Gaussian noise (sigma=0.01) before submitting. This is
enforced on the client side; the server stores whatever it receives.

Storage: SQLite BLOBs inside coordinator.db. No filesystem paths — no path
traversal risk. Blobs are compressed npz, ~20-30 KB each.

Aggregation triggers when AGGREGATE_EVERY_N unapplied contributions accumulate,
or can be triggered manually via aggregate().
"""

import io
import logging
import sqlite3
import time
import uuid
from contextlib import contextmanager
from typing import Optional

import numpy as np

from coordinator.contributor import TIERS, tier_for_params

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────

AGGREGATE_EVERY_N = 5
MIN_CONTRIBUTORS  = 2
MAX_PENDING       = 200       # drop oldest unapplied contributions past this cap
MAX_BLOB_BYTES    = 512_000   # 512 KB hard cap per submission

# Expected npz keys (Qwen2.5-Coder-3B ELC adapter)
_KEYS        = ("k_A", "k_B", "v_A", "v_B")
_HIDDEN_DIM  = 2048
_KV_PROJ_OUT = 256
_RANK_MIN    = 4
_RANK_MAX    = 8    # ARA hard cap — see node/rank_expansion.py

# ── Schema ─────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS fed_contributions (
    id           TEXT    PRIMARY KEY,
    node_id      TEXT    NOT NULL,
    tier         TEXT    NOT NULL,
    weight       REAL    NOT NULL,
    submitted_at REAL    NOT NULL,
    applied      INTEGER NOT NULL DEFAULT 0,
    adapter_blob BLOB    NOT NULL
);

CREATE TABLE IF NOT EXISTS fed_global_state (
    id             INTEGER PRIMARY KEY CHECK (id = 1),
    version        INTEGER NOT NULL DEFAULT 0,
    updated_at     REAL    NOT NULL DEFAULT 0,
    n_contributors INTEGER NOT NULL DEFAULT 0,
    adapter_blob   BLOB
);

INSERT OR IGNORE INTO fed_global_state (id, version, updated_at, n_contributors)
VALUES (1, 0, 0, 0);
"""


def _pad_to_rank(arrays: dict, target_rank: int) -> dict:
    """
    Zero-pad k_A, k_B, v_A, v_B from their current rank to target_rank.
    Padded slots contribute zero to the weighted average — correct behavior
    for nodes that haven't expanded their adapter yet.
    """
    current_rank = int(arrays["k_A"].shape[0])
    if current_rank == target_rank:
        return arrays
    n_new = target_rank - current_rank
    result = {}
    for k in ("k_A", "v_A"):   # (rank, hidden_dim) — pad rows
        result[k] = np.concatenate(
            [arrays[k], np.zeros((n_new, _HIDDEN_DIM), dtype=np.float64)], axis=0
        )
    for k in ("k_B", "v_B"):   # (proj_out, rank) — pad columns
        result[k] = np.concatenate(
            [arrays[k], np.zeros((_KV_PROJ_OUT, n_new), dtype=np.float64)], axis=1
        )
    return result


class FederatedStore:
    """
    SQLite-backed store and FedAvg engine for LoRA adapter contributions.
    Thread-safe: each public method opens/closes its own connection.
    """

    def __init__(self, db_path: str = "coordinator.db"):
        self.db_path   = db_path
        self._mem_conn = None
        if db_path == ":memory:":
            self._mem_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._mem_conn.row_factory = sqlite3.Row
        self._init_db()

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

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    # ── Validation ────────────────────────────────────────────────────

    @staticmethod
    def _valid_blob(blob: bytes) -> bool:
        """
        Returns True if blob is a valid ELC adapter npz with internally
        consistent shapes. Accepts rank 4-8 (ARA variable-rank adapters).
        """
        try:
            data = np.load(io.BytesIO(blob), allow_pickle=False)
            if not all(k in data.files for k in _KEYS):
                return False
            rank = int(data["k_A"].shape[0])
            if not (_RANK_MIN <= rank <= _RANK_MAX):
                return False
            return (
                data["k_A"].shape == (rank, _HIDDEN_DIM) and
                data["k_B"].shape == (_KV_PROJ_OUT, rank) and
                data["v_A"].shape == (rank, _HIDDEN_DIM) and
                data["v_B"].shape == (_KV_PROJ_OUT, rank)
            )
        except Exception:
            return False

    # ── Public API ────────────────────────────────────────────────────

    def add_contribution(
        self,
        node_id:        str,
        total_params_b: float,
        adapter_blob:   bytes,
    ) -> Optional[str]:
        """
        Stores a node's LoRA adapter contribution.
        Returns contribution UUID on success, None on validation failure.
        Triggers FedAvg automatically when AGGREGATE_EVERY_N threshold is reached.
        """
        if len(adapter_blob) > MAX_BLOB_BYTES:
            logger.warning("fed: blob from %s too large (%d bytes)", node_id[:8], len(adapter_blob))
            return None
        if not self._valid_blob(adapter_blob):
            logger.warning("fed: invalid adapter shape from node %s", node_id[:8])
            return None

        tier   = tier_for_params(total_params_b)
        weight = TIERS[tier]["min_params_b"] if tier != "none" else 0.0
        if weight <= 0.0:
            return None

        contrib_id = str(uuid.uuid4())
        now        = time.time()

        with self._conn() as conn:
            pending = conn.execute(
                "SELECT COUNT(*) FROM fed_contributions WHERE applied=0"
            ).fetchone()[0]

            if pending >= MAX_PENDING:
                excess = pending - MAX_PENDING + 1
                conn.execute(
                    """DELETE FROM fed_contributions WHERE id IN (
                           SELECT id FROM fed_contributions
                           WHERE applied=0 ORDER BY submitted_at ASC LIMIT ?
                       )""",
                    (excess,),
                )

            conn.execute(
                """INSERT INTO fed_contributions
                   (id, node_id, tier, weight, submitted_at, applied, adapter_blob)
                   VALUES (?,?,?,?,?,0,?)""",
                (contrib_id, node_id, tier, weight, now, adapter_blob),
            )

            new_pending = conn.execute(
                "SELECT COUNT(*) FROM fed_contributions WHERE applied=0"
            ).fetchone()[0]

        logger.info(
            "fed: contribution %s from %s (tier=%s weight=%.1f pending=%d)",
            contrib_id[:8], node_id[:8], tier, weight, new_pending,
        )

        if new_pending >= AGGREGATE_EVERY_N:
            self.aggregate()

        return contrib_id

    def get_global_adapter(self) -> Optional[bytes]:
        """Returns the current global adapter blob, or None if not yet computed."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT adapter_blob FROM fed_global_state WHERE id=1"
            ).fetchone()
        return bytes(row["adapter_blob"]) if (row and row["adapter_blob"]) else None

    def aggregate(self) -> bool:
        """
        Runs FedAvg over all unapplied contributions.
        Returns True if a new global adapter was produced.
        Called automatically by add_contribution; can also be called manually.

        Supports variable-rank adapters (ARA): finds the max rank across
        the batch, pads smaller contributions with zeros before averaging.
        The global adapter is saved at the batch's max rank.
        """
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT id, weight, adapter_blob FROM fed_contributions
                   WHERE applied=0 ORDER BY submitted_at ASC"""
            ).fetchall()

        if len(rows) < MIN_CONTRIBUTORS:
            return False

        # Pass 1: deserialize and validate; find max rank
        loaded = []
        for row in rows:
            try:
                data = np.load(io.BytesIO(bytes(row["adapter_blob"])), allow_pickle=False)
                loaded.append((row, data))
            except Exception as exc:
                logger.warning("fed: skipping corrupt contribution %s: %s", row["id"][:8], exc)

        if len(loaded) < MIN_CONTRIBUTORS:
            return False

        total_weight = sum(float(r["weight"]) for r, _ in loaded)
        if total_weight <= 0.0:
            return False

        max_rank = max(int(d["k_A"].shape[0]) for _, d in loaded)

        # Pass 2: weighted accumulation with rank padding
        acc = {
            "k_A": np.zeros((max_rank, _HIDDEN_DIM),  dtype=np.float64),
            "k_B": np.zeros((_KV_PROJ_OUT, max_rank), dtype=np.float64),
            "v_A": np.zeros((max_rank, _HIDDEN_DIM),  dtype=np.float64),
            "v_B": np.zeros((_KV_PROJ_OUT, max_rank), dtype=np.float64),
        }
        valid_ids = []

        for row, data in loaded:
            w      = float(row["weight"]) / total_weight
            padded = _pad_to_rank({k: data[k].astype(np.float64) for k in _KEYS}, max_rank)
            for k in _KEYS:
                acc[k] += w * padded[k]
            valid_ids.append(row["id"])

        buf = io.BytesIO()
        np.savez_compressed(
            buf,
            k_A=acc["k_A"].astype(np.float32),
            k_B=acc["k_B"].astype(np.float32),
            v_A=acc["v_A"].astype(np.float32),
            v_B=acc["v_B"].astype(np.float32),
        )
        global_blob = buf.getvalue()

        now = time.time()
        with self._conn() as conn:
            conn.execute(
                """UPDATE fed_global_state
                   SET version=version+1, updated_at=?, n_contributors=?, adapter_blob=?
                   WHERE id=1""",
                (now, len(valid_ids), global_blob),
            )
            placeholders = ",".join("?" * len(valid_ids))
            conn.execute(
                f"UPDATE fed_contributions SET applied=1 WHERE id IN ({placeholders})",
                valid_ids,
            )

        logger.info(
            "fed: FedAvg v%d complete — %d contributors rank=%d",
            self._version(), len(valid_ids), max_rank,
        )
        return True

    def stats(self) -> dict:
        with self._conn() as conn:
            state   = conn.execute(
                "SELECT version, updated_at, n_contributors FROM fed_global_state WHERE id=1"
            ).fetchone()
            pending = conn.execute(
                "SELECT COUNT(*) FROM fed_contributions WHERE applied=0"
            ).fetchone()[0]
            total   = conn.execute(
                "SELECT COUNT(*) FROM fed_contributions"
            ).fetchone()[0]
        return {
            "global_version":        state["version"]        if state else 0,
            "last_aggregated_at":    state["updated_at"]     if state else 0,
            "n_contributors_last":   state["n_contributors"] if state else 0,
            "pending_contributions": pending,
            "total_contributions":   total,
            "aggregate_every_n":     AGGREGATE_EVERY_N,
            "min_contributors":      MIN_CONTRIBUTORS,
        }

    def _version(self) -> int:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT version FROM fed_global_state WHERE id=1"
            ).fetchone()
        return row["version"] if row else 0
