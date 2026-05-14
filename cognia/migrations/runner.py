"""
cognia/migrations/runner.py
===========================
Versioned SQLite schema migration runner.

Each migration is a plain function that receives a sqlite3.Connection and
modifies the schema. Migrations are identified by a monotonically increasing
integer version number and are idempotent (safe to call if already applied).

The current schema version is stored in the existing `schema_version` table
created by cognia/database.py.

Usage:
    from cognia.migrations import run_migrations
    run_migrations(db_path)

Adding a new migration:
    1. Write a function  def migration_N(conn): ...
    2. Add it to MIGRATIONS at the end with the next version number.
    3. Never edit or reorder existing entries.
"""

import sqlite3
import logging

logger = logging.getLogger(__name__)


# ── Migration functions ────────────────────────────────────────────────

def _migration_1(conn: sqlite3.Connection) -> None:
    """Add feedback_weight to episodic_memory (already in database.py; kept for parity)."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(episodic_memory)").fetchall()}
    if "feedback_weight" not in cols:
        conn.execute(
            "ALTER TABLE episodic_memory ADD COLUMN feedback_weight REAL DEFAULT 1.0"
        )


def _migration_2(conn: sqlite3.Connection) -> None:
    """Add encrypted_at flag to episodic_memory for tracking column-level encryption status."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(episodic_memory)").fetchall()}
    if "encrypted_at" not in cols:
        conn.execute(
            "ALTER TABLE episodic_memory ADD COLUMN encrypted_at TEXT DEFAULT NULL"
        )


def _migration_3(conn: sqlite3.Connection) -> None:
    """Add app_version column to schema_version table for tracking which Cognia version applied each migration."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(schema_version)").fetchall()}
    if "app_version" not in cols:
        conn.execute(
            "ALTER TABLE schema_version ADD COLUMN app_version TEXT DEFAULT NULL"
        )
    if "applied_at" not in cols:
        conn.execute(
            "ALTER TABLE schema_version ADD COLUMN applied_at TEXT DEFAULT NULL"
        )


# ── Migration registry ─────────────────────────────────────────────────
# List of (version, function) pairs. Version must be strictly increasing.
# Never remove or reorder entries.

MIGRATIONS: list[tuple[int, callable]] = [
    (1, _migration_1),
    (2, _migration_2),
    (3, _migration_3),
]


# ── Runner ─────────────────────────────────────────────────────────────

class MigrationRunner:
    """
    Applies pending schema migrations to a SQLite database.

    Reads current version from schema_version table, applies all
    pending migrations in order, updates the version after each one.
    """

    def __init__(self, db_path: str):
        self._db_path = db_path

    def _current_version(self, conn: sqlite3.Connection) -> int:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)
        """)
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        return row[0] if row else 0

    def _set_version(self, conn: sqlite3.Connection, version: int) -> None:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        existing = conn.execute("SELECT version FROM schema_version").fetchone()
        if existing:
            conn.execute(
                "UPDATE schema_version SET version=?, applied_at=?",
                (version, now),
            )
        else:
            conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)",
                (version,),
            )

    def run(self) -> int:
        """
        Apply all pending migrations.
        Returns the number of migrations applied.
        """
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.text_factory = str
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")

        try:
            current = self._current_version(conn)
            applied = 0

            for version, fn in MIGRATIONS:
                if version <= current:
                    continue
                logger.info("Applying migration %d: %s", version, fn.__name__)
                fn(conn)
                self._set_version(conn, version)
                conn.commit()
                applied += 1
                logger.info("Migration %d applied successfully.", version)

            if applied == 0:
                logger.debug("Schema is up to date at version %d.", current)
            else:
                new_version = self._current_version(conn)
                logger.info(
                    "Applied %d migration(s). Schema version: %d -> %d.",
                    applied, current, new_version,
                )

            return applied

        finally:
            conn.close()


def run_migrations(db_path: str) -> int:
    """Convenience wrapper. Returns count of applied migrations."""
    return MigrationRunner(db_path).run()
