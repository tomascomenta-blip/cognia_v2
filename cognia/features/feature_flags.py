"""
cognia/features/feature_flags.py
=================================
Lightweight feature flag system tied to API tiers.
Allows enabling/disabling features per user/tier without code changes.

Usage:
    from cognia.features.feature_flags import FeatureFlagManager
    mgr = FeatureFlagManager(db_path="cognia_desktop_chat.db")
    if mgr.is_enabled("proactive_engine", tier="free"):
        ...
"""

from __future__ import annotations

import time
from typing import Optional

from storage.db_pool import get_pool

_TIER_RANK: dict[str, int] = {
    "free": 0,
    "pro": 1,
    "enterprise": 2,
    "local": 3,
}

_DEFAULT_FLAGS: list[tuple] = [
    ("semantic_search",    1, "free",       "Busqueda semantica TF-IDF en historial"),
    ("proactive_engine",   1, "free",       "Sugerencias proactivas post-infer"),
    ("auto_notes",         1, "free",       "Extraccion automatica de notas"),
    ("feedback_learning",  1, "free",       "Aprendizaje por retroalimentacion implicita"),
    ("long_term_memory",   1, "free",       "Consolidacion de memoria a largo plazo"),
    ("self_critique",      1, "pro",        "Autocritica y mejora de respuestas"),
    ("recommendations",    1, "pro",        "Motor de recomendaciones personalizadas"),
    ("achievements",       1, "free",       "Sistema de logros y gamificacion"),
    ("spaced_repetition",  1, "free",       "Aprendizaje espaciado SM-2"),
    ("debug_endpoints",    0, "enterprise", "Endpoints de debug y estado interno"),
]


class FeatureFlagManager:
    """Manages feature flags stored in SQLite, gated by API tier."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db = db_path
        self._init_table()
        self._seed_defaults()

    # ── Private helpers ────────────────────────────────────────────────

    def _init_table(self) -> None:
        with get_pool(self._db).get() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS feature_flags ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  name TEXT UNIQUE NOT NULL,"
                "  enabled_default INTEGER NOT NULL DEFAULT 1,"
                "  min_tier TEXT NOT NULL DEFAULT 'free',"
                "  description TEXT NOT NULL DEFAULT '',"
                "  updated_at REAL NOT NULL DEFAULT 0"
                ")"
            )

    def _seed_defaults(self) -> None:
        now = time.time()
        with get_pool(self._db).get() as conn:
            for name, enabled, min_tier, desc in _DEFAULT_FLAGS:
                conn.execute(
                    "INSERT OR IGNORE INTO feature_flags "
                    "(name, enabled_default, min_tier, description, updated_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (name, enabled, min_tier, desc, now),
                )

    # ── Public API ─────────────────────────────────────────────────────

    def is_enabled(self, name: str, tier: str = "free") -> bool:
        """Return True if flag exists, is enabled, and tier rank >= min_tier rank."""
        with get_pool(self._db).get() as conn:
            row = conn.execute(
                "SELECT enabled_default, min_tier FROM feature_flags WHERE name = ?",
                (name,),
            ).fetchone()
        if row is None:
            return False
        enabled_default, min_tier = row
        if not enabled_default:
            return False
        caller_rank = _TIER_RANK.get(tier, 0)
        required_rank = _TIER_RANK.get(min_tier, 0)
        return caller_rank >= required_rank

    def get_all(self) -> list[dict]:
        """Return all flags as list of dicts with name/enabled_default/min_tier/description."""
        with get_pool(self._db).get() as conn:
            rows = conn.execute(
                "SELECT name, enabled_default, min_tier, description FROM feature_flags "
                "ORDER BY name"
            ).fetchall()
        return [
            {"name": r[0], "enabled_default": bool(r[1]), "min_tier": r[2], "description": r[3]}
            for r in rows
        ]

    def set_flag(self, name: str, enabled: bool) -> bool:
        """Update enabled_default for flag. Returns True if row existed."""
        with get_pool(self._db).get() as conn:
            row = conn.execute(
                "SELECT id FROM feature_flags WHERE name = ?", (name,)
            ).fetchone()
            if row is None:
                return False
            conn.execute(
                "UPDATE feature_flags SET enabled_default = ?, updated_at = ? WHERE name = ?",
                (1 if enabled else 0, time.time(), name),
            )
        return True

    def get_accessible(self, tier: str) -> list[str]:
        """Return names of all flags accessible to the given tier (regardless of enabled state)."""
        caller_rank = _TIER_RANK.get(tier, 0)
        with get_pool(self._db).get() as conn:
            rows = conn.execute(
                "SELECT name, min_tier FROM feature_flags ORDER BY name"
            ).fetchall()
        return [
            r[0] for r in rows
            if _TIER_RANK.get(r[1], 0) <= caller_rank
        ]
