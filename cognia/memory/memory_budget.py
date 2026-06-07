"""
cognia/memory/memory_budget.py
=============================
Configurable cap on how much space episodic memory may use, enforced by purging
the LOWEST-VALUE memories first. Two independent limits; whichever is hit triggers
a purge:

  COGNIA_MAX_MEMORIES  -- max active (forgotten=0) episodes.
  COGNIA_MAX_DB_MB     -- max size of the DB file on disk, in MB.

Either unset / <= 0 means "no limit on that axis".

Value ranking (worst purged first): already-forgotten rows, then lowest
feedback_weight, fewest accesses, lowest importance, lowest confidence, oldest id.
This mirrors the consolidation engine's notion of "low value" but applies a HARD
ceiling instead of trimming a fixed batch.

Count cap -> soft-delete (forgotten=1): the memory stays recoverable but stops
counting as active. Disk cap -> hard DELETE of the worst rows + VACUUM, because
soft-deleted rows still occupy disk.
"""

from __future__ import annotations

import os

from storage.db_pool import db_connect_pooled
from ..config import DB_PATH

# Worst-first ordering used by every purge query.
_WORST_FIRST = (
    "ORDER BY forgotten DESC, COALESCE(feedback_weight,1.0) ASC, "
    "COALESCE(access_count,0) ASC, COALESCE(importance,1.0) ASC, "
    "COALESCE(confidence,0.5) ASC, id ASC"
)


def get_limits() -> tuple:
    """(max_count, max_mb) from env; None where unset or non-positive."""
    def _pos_int(name):
        try:
            v = int(float(os.environ.get(name, "0")))
            return v if v > 0 else None
        except Exception:
            return None
    return _pos_int("COGNIA_MAX_MEMORIES"), _pos_int("COGNIA_MAX_DB_MB")


def db_size_mb(db_path: str = DB_PATH) -> float:
    """Size of the DB file (plus its -wal sidecar) in MB."""
    total = 0
    for suffix in ("", "-wal", "-shm"):
        try:
            total += os.path.getsize(db_path + suffix)
        except OSError:
            pass
    return total / (1024 * 1024)


def current_usage(db_path: str = DB_PATH) -> dict:
    """{active, total, mb} -- active episodes, total rows, file size."""
    conn = db_connect_pooled(db_path)
    try:
        active = conn.execute(
            "SELECT COUNT(*) FROM episodic_memory WHERE forgotten = 0"
        ).fetchone()[0]
        total = conn.execute("SELECT COUNT(*) FROM episodic_memory").fetchone()[0]
    finally:
        conn.close()
    return {"active": active, "total": total, "mb": round(db_size_mb(db_path), 2)}


def enforce_memory_budget(db_path: str = DB_PATH, max_count: int = None,
                          max_mb: float = None) -> dict:
    """
    Bring memory under both caps. Returns a report dict. Never raises.

    max_count / max_mb default to get_limits(); pass explicit values to override
    (e.g. tests). Unset axis = not enforced.
    """
    if max_count is None and max_mb is None:
        max_count, max_mb = get_limits()

    before = current_usage(db_path)
    soft_deleted = 0
    hard_deleted = 0

    conn = db_connect_pooled(db_path)
    try:
        # --- Count cap: soft-delete worst active rows down to the limit ---
        if max_count and before["active"] > max_count:
            to_remove = before["active"] - max_count
            ids = [r[0] for r in conn.execute(
                f"SELECT id FROM episodic_memory WHERE forgotten = 0 "
                f"{_WORST_FIRST} LIMIT ?", (to_remove,)
            ).fetchall()]
            if ids:
                conn.executemany(
                    "UPDATE episodic_memory SET forgotten = 1 WHERE id = ?",
                    [(i,) for i in ids],
                )
                conn.commit()
                soft_deleted = len(ids)

        # --- Disk cap: hard-delete the worst rows, then VACUUM once ---
        # Soft-deleted rows still occupy disk, so this must DELETE. We estimate
        # how many rows to drop from the current bytes/row, keep a 50-row floor,
        # then VACUUM a single time (cheaper than per-batch) to shrink the file.
        if max_mb and db_size_mb(db_path) > max_mb:
            total_rows = conn.execute(
                "SELECT COUNT(*) FROM episodic_memory"
            ).fetchone()[0]
            cur_mb = db_size_mb(db_path)
            if total_rows > 50 and cur_mb > 0:
                mb_per_row = cur_mb / total_rows
                n_del = int((cur_mb - max_mb) / mb_per_row) + 1 if mb_per_row > 0 else 0
                n_del = min(n_del, total_rows - 50)  # never go below the floor
                if n_del > 0:
                    ids = [r[0] for r in conn.execute(
                        f"SELECT id FROM episodic_memory {_WORST_FIRST} LIMIT ?",
                        (n_del,)
                    ).fetchall()]
                    conn.executemany(
                        "DELETE FROM episodic_memory WHERE id = ?",
                        [(i,) for i in ids],
                    )
                    conn.commit()
                    hard_deleted = len(ids)
    finally:
        conn.close()

    # Reclaim disk AFTER releasing the pooled connection: vacuum() checkpoints the
    # WAL and VACUUMs on a dedicated autocommit connection (it closes the pool for
    # this path first, so it must run with no pooled conn held).
    if hard_deleted:
        try:
            from storage.db_pool import vacuum as _vacuum
            _vacuum(db_path)
        except Exception:
            pass

    after = current_usage(db_path)
    # Keep the fast vector cache honest after a purge.
    try:
        from .episodic_fast import invalidate_cache
        invalidate_cache(db_path)
    except Exception:
        pass

    return {
        "max_count": max_count, "max_mb": max_mb,
        "soft_deleted": soft_deleted, "hard_deleted": hard_deleted,
        "before": before, "after": after,
        "enforced": bool(soft_deleted or hard_deleted),
    }
