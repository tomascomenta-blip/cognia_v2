"""
context_map.py
==============
Context Map Cycle 1 (keystone): pointer index over text that lives on disk.

A pointer stores (source_ref, char_start, char_end) instead of the text itself,
so re-reading the original by offset is lossless and O(1) in space per chunk.
context_coverage tracks which part of each source is already indexed, for the
later gap-filling cycle. See cognia/context/CONTEXT_MAP_DESIGN.md.
"""

import json
import time
from pathlib import Path

from storage.db_pool import get_pool

try:
    from cognia.config import DB_PATH as _DEFAULT_DB_PATH
except ImportError:
    _DEFAULT_DB_PATH = None


_POINTER_COLUMNS = (
    "id", "project", "source_kind", "source_ref", "char_start", "char_end",
    "chunk_ord", "label", "summary", "inline_text", "vector", "importance",
    "created_at",
)


class ContextMap:
    def __init__(self, db_path=None, project="default"):
        self.db_path = db_path if db_path is not None else _DEFAULT_DB_PATH
        self.project = project
        self._ensure_schema()

    def _ensure_schema(self):
        with get_pool(self.db_path).get() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS context_pointers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project TEXT NOT NULL,
                    source_kind TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    char_start INTEGER,
                    char_end INTEGER,
                    chunk_ord INTEGER,
                    label TEXT,
                    summary TEXT,
                    inline_text TEXT,
                    vector TEXT,
                    importance REAL DEFAULT 1.0,
                    created_at REAL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS context_coverage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    indexed_through INTEGER,
                    total_chars INTEGER,
                    mtime REAL,
                    updated_at REAL,
                    UNIQUE(project, source_ref)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ptr_project ON context_pointers(project)"
            )

    def add_pointer(self, source_kind, source_ref, char_start=None, char_end=None,
                    chunk_ord=0, label=None, summary=None, inline_text=None,
                    vector=None, importance=1.0):
        vector_json = json.dumps(vector) if isinstance(vector, list) else None
        with get_pool(self.db_path).get() as conn:
            cur = conn.execute(
                """
                INSERT INTO context_pointers
                    (project, source_kind, source_ref, char_start, char_end,
                     chunk_ord, label, summary, inline_text, vector, importance,
                     created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (self.project, source_kind, source_ref, char_start, char_end,
                 chunk_ord, label, summary, inline_text, vector_json, importance,
                 time.time()),
            )
            return cur.lastrowid

    def resolve(self, pointer_id):
        with get_pool(self.db_path).get() as conn:
            row = conn.execute(
                "SELECT source_kind, source_ref, char_start, char_end, inline_text "
                "FROM context_pointers WHERE id = ?",
                (pointer_id,),
            ).fetchone()
        if row is None:
            return None
        source_kind, source_ref, char_start, char_end, inline_text = row
        if source_kind == "file":
            try:
                txt = Path(source_ref).read_text(encoding="utf-8", errors="replace")
            except OSError:
                return None
            return txt[char_start:char_end]
        if source_kind == "text":
            return inline_text
        if source_kind == "msg":
            return None
        return None

    def mark_coverage(self, source_ref, indexed_through, total_chars, mtime=0.0):
        with get_pool(self.db_path).get() as conn:
            conn.execute(
                """
                INSERT INTO context_coverage
                    (project, source_ref, indexed_through, total_chars, mtime, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(project, source_ref) DO UPDATE SET
                    indexed_through=excluded.indexed_through,
                    total_chars=excluded.total_chars,
                    mtime=excluded.mtime,
                    updated_at=excluded.updated_at
                """,
                (self.project, source_ref, indexed_through, total_chars, mtime,
                 time.time()),
            )

    def uncovered(self, source_ref):
        with get_pool(self.db_path).get() as conn:
            row = conn.execute(
                "SELECT indexed_through, total_chars FROM context_coverage "
                "WHERE project = ? AND source_ref = ?",
                (self.project, source_ref),
            ).fetchone()
        if row is None:
            return None
        indexed_through, total_chars = row
        if total_chars > indexed_through:
            return (indexed_through, total_chars)
        return None

    def pointers(self, project=None):
        proj = project if project is not None else self.project
        with get_pool(self.db_path).get() as conn:
            rows = conn.execute(
                "SELECT " + ", ".join(_POINTER_COLUMNS) +
                " FROM context_pointers WHERE project = ? ORDER BY chunk_ord, id",
                (proj,),
            ).fetchall()
        return [dict(zip(_POINTER_COLUMNS, r)) for r in rows]

    def stats(self):
        with get_pool(self.db_path).get() as conn:
            n_ptr = conn.execute(
                "SELECT COUNT(*) FROM context_pointers WHERE project = ?",
                (self.project,),
            ).fetchone()[0]
            n_cov = conn.execute(
                "SELECT COUNT(*) FROM context_coverage WHERE project = ?",
                (self.project,),
            ).fetchone()[0]
        return {"pointers": n_ptr, "covered_sources": n_cov}
