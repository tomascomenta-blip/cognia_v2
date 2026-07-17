"""
coordinator/contributor.py
==========================
Economic layer for the Cognia swarm.

Nodes that contribute model parameters (shards) receive a contributor token
that grants free API access. More parameters contributed → higher tier →
better rate limits and model access.

Token format: stateless HMAC-SHA256, {node_id}.{hex_signature}
Ledger:       coordinator.db / contributor_ledger table
"""

import hashlib
import hmac
import sqlite3
import time
from contextlib import contextmanager
from typing import Optional


# ── Tier definitions ──────────────────────────────────────────────────
# Ordered by ascending min_params_b. "none" is the fallback for non-contributors.

TIERS: dict = {
    "none": {
        "min_params_b":   0.0,
        "rpm":            0,
        "allowed_models": [],
        "description":    "No contribution. Inference access denied.",
    },
    "basic": {
        "min_params_b":   0.5,
        "rpm":            10,
        "allowed_models": ["qwen-coder-3b-q4"],
        "description":    ">=0.5B params. Standard model, 10 RPM.",
    },
    "standard": {
        "min_params_b":   1.0,
        "rpm":            30,
        "allowed_models": [
            "qwen-coder-3b-q4", "llama-3.1-8b-q4",
            "logos-3.2-3b-q4", "techne-3.2-3b-q4", "rhetor-3.2-3b-q4",
        ],
        "description":    ">=1.0B params. Standard + 8B + Shattering models, 30 RPM.",
    },
    "premium": {
        "min_params_b":   3.0,
        "rpm":            100,
        "allowed_models": ["*"],
        "description":    ">=3.0B params. Full model access, 100 RPM.",
    },
}


def tier_for_params(total_params_b: float) -> str:
    for name in ("premium", "standard", "basic"):
        if total_params_b >= TIERS[name]["min_params_b"]:
            return name
    return "none"


# ── Token generation / validation ─────────────────────────────────────

def generate_token(coordinator_key: str, node_id: str) -> str:
    """
    Stateless HMAC-SHA256 contributor token.
    Requires non-empty coordinator_key; raises ValueError otherwise.
    """
    if not coordinator_key:
        raise ValueError("Cannot generate contributor token: COORDINATOR_KEY is not set.")
    sig = hmac.new(
        coordinator_key.encode(),
        node_id.encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{node_id}.{sig}"


def validate_token(coordinator_key: str, token: str) -> Optional[str]:
    """
    Returns node_id if the token signature is valid, None otherwise.
    Constant-time comparison prevents timing side-channels.
    """
    if not coordinator_key or not token:
        return None
    try:
        node_id, sig = token.rsplit(".", 1)
    except ValueError:
        return None
    expected = hmac.new(
        coordinator_key.encode(),
        node_id.encode(),
        hashlib.sha256,
    ).hexdigest()
    if hmac.compare_digest(expected, sig):
        return node_id
    return None


# ── Ledger ────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS contributor_ledger (
    node_id         TEXT    PRIMARY KEY,
    total_params_b  REAL    NOT NULL DEFAULT 0.0,
    first_seen      REAL    NOT NULL,
    last_seen       REAL    NOT NULL,
    requests_served INTEGER NOT NULL DEFAULT 0
);
"""


class ContributorLedger:
    """
    SQLite-backed ledger tracking per-node parameter contributions.
    Uses the same coordinator.db as NodeRegistry to avoid multiple DB files.
    """

    def __init__(self, db_path: str = "coordinator.db"):
        self.db_path = db_path
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
            from storage.db_pool import db_connect_pooled
            conn = db_connect_pooled(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    def record_contribution(self, node_id: str, params_b: float):
        """
        Adds params_b to the node's ledger balance.
        Called once per node registration; params_b is the shard's share of the model.
        """
        now = time.time()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT total_params_b FROM contributor_ledger WHERE node_id=?",
                (node_id,),
            ).fetchone()
            if row:
                conn.execute(
                    """UPDATE contributor_ledger
                       SET total_params_b=?, last_seen=?
                       WHERE node_id=?""",
                    (row["total_params_b"] + params_b, now, node_id),
                )
            else:
                conn.execute(
                    """INSERT INTO contributor_ledger
                       (node_id, total_params_b, first_seen, last_seen, requests_served)
                       VALUES (?,?,?,?,0)""",
                    (node_id, params_b, now, now),
                )

    def increment_requests(self, node_id: str):
        with self._conn() as conn:
            conn.execute(
                """UPDATE contributor_ledger
                   SET requests_served = requests_served + 1, last_seen = ?
                   WHERE node_id = ?""",
                (time.time(), node_id),
            )

    def get_contribution(self, node_id: str) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM contributor_ledger WHERE node_id=?", (node_id,)
            ).fetchone()
        if not row:
            return None
        total     = row["total_params_b"]
        tier_name = tier_for_params(total)
        return {
            "node_id":         row["node_id"],
            "total_params_b":  total,
            "tier":            tier_name,
            "tier_info":       TIERS[tier_name],
            "first_seen":      row["first_seen"],
            "last_seen":       row["last_seen"],
            "requests_served": row["requests_served"],
        }

    def get_tier_for_node(self, node_id: str) -> str:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT total_params_b FROM contributor_ledger WHERE node_id=?",
                (node_id,),
            ).fetchone()
        if not row:
            return "none"
        return tier_for_params(row["total_params_b"])
