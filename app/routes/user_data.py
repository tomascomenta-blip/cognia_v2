"""
app/routes/user_data.py
=======================
GDPR-aligned user data endpoints:
  GET  /api/user/data/export  — export all personal episodic memory as JSON
  DELETE /api/user/data       — soft-delete all episodic memory (right to erasure)

Authentication: X-Admin-Key header must match COGNIA_ADMIN_KEY env var.
If COGNIA_ADMIN_KEY is not set, both endpoints return 503 (fail-safe).
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi import APIRouter, HTTPException, Header
from typing import Optional

router = APIRouter()

_ADMIN_KEY = os.environ.get("COGNIA_ADMIN_KEY", "")


def _require_admin_key(x_admin_key: Optional[str] = Header(None)) -> None:
    if not _ADMIN_KEY:
        raise HTTPException(
            status_code=503,
            detail="User data endpoints are not configured. Set COGNIA_ADMIN_KEY.",
        )
    if x_admin_key != _ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin key.")


def _get_db_path() -> str:
    try:
        from cognia.config import DB_PATH
        return DB_PATH
    except ImportError:
        return "cognia_memory.db"


@router.get("/user/data/export")
def export_user_data(x_admin_key: Optional[str] = Header(None)):
    """
    Export all non-forgotten episodic memory rows as JSON.
    Intended for privacy/GDPR data access requests.
    """
    _require_admin_key(x_admin_key)

    try:
        from cognia.database import db_connect
        conn = db_connect(_get_db_path())
        rows = conn.execute(
            """
            SELECT id, timestamp, observation, label, confidence,
                   emotion_label, context_tags, notes
            FROM episodic_memory
            WHERE forgotten = 0
            ORDER BY timestamp DESC
            """
        ).fetchall()
        conn.close()
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Could not read user data. Please try again.",
        )

    records = [
        {
            "id":           r[0],
            "timestamp":    r[1],
            "observation":  r[2],
            "label":        r[3],
            "confidence":   r[4],
            "emotion":      r[5],
            "context_tags": r[6],
            "notes":        r[7],
        }
        for r in rows
    ]
    return {"count": len(records), "records": records}


@router.delete("/user/data")
def delete_user_data(x_admin_key: Optional[str] = Header(None)):
    """
    Soft-delete all episodic memory (sets forgotten=1).
    Irreversible via API. Right to erasure (GDPR Art. 17).

    WARNING: Cognia is single-user. This endpoint deletes ALL stored memory
    regardless of which user created it. There is no per-user scoping.
    """
    _require_admin_key(x_admin_key)

    try:
        from cognia.database import db_connect
        conn = db_connect(_get_db_path())
        result = conn.execute(
            "UPDATE episodic_memory SET forgotten=1 WHERE forgotten=0"
        )
        deleted = result.rowcount
        conn.commit()
        conn.close()
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Could not delete user data. Please try again.",
        )

    return {
        "deleted": deleted,
        "status": "ok",
        "scope": "all",
        "warning": (
            "Cognia is single-user. All episodic memory was deleted, "
            "regardless of origin. There is no per-user scoping."
        ),
    }
