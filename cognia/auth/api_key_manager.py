"""
cognia/auth/api_key_manager.py
==============================
Per-user API key management for Cognia Desktop API.

Keys are stored as SHA-256 hashes (no plaintext persisted).
Prefix: cognia_sk_<uuid4 without dashes>

Usage:
    mgr = APIKeyManager(db_path="cognia_desktop_chat.db")
    raw_key = mgr.create_key("user123", label="my integration")
    user_id = mgr.validate_key(raw_key)  # -> "user123"
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Optional

from storage.db_pool import get_pool

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS api_keys (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      TEXT    NOT NULL,
    label        TEXT    NOT NULL DEFAULT '',
    key_hash     TEXT    NOT NULL UNIQUE,
    created_at   INTEGER NOT NULL DEFAULT (strftime('%s','now')),
    last_used_at INTEGER,
    active       INTEGER NOT NULL DEFAULT 1
)
"""

_ALTER_ADD_TIER = "ALTER TABLE api_keys ADD COLUMN tier TEXT NOT NULL DEFAULT 'free'"

_CREATE_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash)"
)


def _sha256(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class APIKeyManager:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        with get_pool(db_path).get() as conn:
            conn.execute(_CREATE_TABLE)
            conn.execute(_CREATE_INDEX)
            # Add tier column to existing databases (idempotent)
            try:
                conn.execute(_ALTER_ADD_TIER)
            except Exception:
                pass  # column already exists

    # ── public API ────────────────────────────────────────────────────

    def create_key(self, user_id: str, label: str = "", tier: str = "free") -> str:
        """Generate a new API key and persist its hash. Returns plaintext key."""
        raw_key = "cognia_sk_" + uuid.uuid4().hex
        key_hash = _sha256(raw_key)
        with get_pool(self._db_path).get() as conn:
            conn.execute(
                "INSERT INTO api_keys (user_id, label, key_hash, tier) VALUES (?, ?, ?, ?)",
                (user_id, label, key_hash, tier),
            )
        return raw_key

    def validate_key(self, raw_key: str) -> Optional[str]:
        """Return user_id if key is valid and active, else None. Updates last_used_at."""
        if not raw_key or not raw_key.startswith("cognia_sk_"):
            return None
        key_hash = _sha256(raw_key)
        with get_pool(self._db_path).get() as conn:
            row = conn.execute(
                "SELECT id, user_id, tier FROM api_keys WHERE key_hash = ? AND active = 1",
                (key_hash,),
            ).fetchone()
            if row is None:
                return None
            key_id, user_id, tier = row
            conn.execute(
                "UPDATE api_keys SET last_used_at = strftime('%s','now') WHERE id = ?",
                (key_id,),
            )
        return user_id

    def validate_key_full(self, raw_key: str) -> Optional[dict]:
        """Return {"user_id": ..., "tier": ...} if key is valid and active, else None."""
        if not raw_key or not raw_key.startswith("cognia_sk_"):
            return None
        key_hash = _sha256(raw_key)
        with get_pool(self._db_path).get() as conn:
            row = conn.execute(
                "SELECT id, user_id, tier FROM api_keys WHERE key_hash = ? AND active = 1",
                (key_hash,),
            ).fetchone()
            if row is None:
                return None
            key_id, user_id, tier = row
            conn.execute(
                "UPDATE api_keys SET last_used_at = strftime('%s','now') WHERE id = ?",
                (key_id,),
            )
        return {"user_id": user_id, "tier": tier or "free"}

    def get_key_tier(self, user_id: str) -> str:
        """Return the tier of the most recently created active key for user_id."""
        with get_pool(self._db_path).get() as conn:
            row = conn.execute(
                "SELECT tier FROM api_keys WHERE user_id = ? AND active = 1"
                " ORDER BY id DESC LIMIT 1",
                (user_id,),
            ).fetchone()
        if row is None:
            return "free"
        return row[0] or "free"

    def revoke_key(self, key_id: int) -> bool:
        """Deactivate a key by id. Returns True if a row was updated."""
        with get_pool(self._db_path).get() as conn:
            cursor = conn.execute(
                "UPDATE api_keys SET active = 0 WHERE id = ?",
                (key_id,),
            )
        return cursor.rowcount > 0

    def list_keys(self, user_id: str) -> list[dict]:
        """Return all keys (no hash) for a given user_id."""
        with get_pool(self._db_path).get() as conn:
            rows = conn.execute(
                "SELECT id, user_id, label, created_at, last_used_at, active, tier"
                " FROM api_keys WHERE user_id = ? ORDER BY id",
                (user_id,),
            ).fetchall()
        return [
            {
                "id":           r[0],
                "user_id":      r[1],
                "label":        r[2],
                "created_at":   r[3],
                "last_used_at": r[4],
                "active":       bool(r[5]),
                "tier":         r[6] or "free",
            }
            for r in rows
        ]
