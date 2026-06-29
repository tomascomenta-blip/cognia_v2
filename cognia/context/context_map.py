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

import numpy as np

from cognia.context.lexical_index import bm25_scores
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
        if vector is None:
            vector_json = None
        else:
            try:
                vector_json = json.dumps([float(x) for x in vector])
            except (TypeError, ValueError):
                vector_json = None
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
            try:
                with get_pool(self.db_path).get() as conn:
                    row2 = conn.execute(
                        "SELECT content FROM chat_history WHERE id = ?", (source_ref,)
                    ).fetchone()
            except Exception:
                return None
            if row2 is None:
                return None
            content = row2[0]
            if char_start is not None and char_end is not None:
                return content[char_start:char_end]
            return content
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

    def uncovered_sources(self, project=None):
        """Sources of `project` with an unindexed tail, for gap-filling.
        Returns a list of (source_ref, indexed_through, total_chars) where
        total_chars > indexed_through."""
        proj = project if project is not None else self.project
        with get_pool(self.db_path).get() as conn:
            rows = conn.execute(
                "SELECT source_ref, indexed_through, total_chars "
                "FROM context_coverage "
                "WHERE project = ? AND total_chars > indexed_through "
                "ORDER BY source_ref",
                (proj,),
            ).fetchall()
        return [(r[0], r[1], r[2]) for r in rows]

    def all_coverage(self, project=None):
        """Every coverage row of `project` (NOT only the ones with a gap), for
        on-disk gap detection: returns a list of
        (source_ref, indexed_through, total_chars) ordered by source_ref."""
        proj = project if project is not None else self.project
        with get_pool(self.db_path).get() as conn:
            rows = conn.execute(
                "SELECT source_ref, indexed_through, total_chars "
                "FROM context_coverage WHERE project = ? ORDER BY source_ref",
                (proj,),
            ).fetchall()
        return [(r[0], r[1], r[2]) for r in rows]

    def pointers(self, project=None):
        proj = project if project is not None else self.project
        with get_pool(self.db_path).get() as conn:
            rows = conn.execute(
                "SELECT " + ", ".join(_POINTER_COLUMNS) +
                " FROM context_pointers WHERE project = ? ORDER BY chunk_ord, id",
                (proj,),
            ).fetchall()
        return [dict(zip(_POINTER_COLUMNS, r)) for r in rows]

    def query(self, query_vector, budget_tokens=4000, top_k=50):
        """Rank this project's pointers by cosine similarity to query_vector and
        return the raw spans (resolved lossless) that fit in budget_tokens.
        Tokens are estimated at ~4 chars/token. Returns a list of dicts
        {id, score, source_kind, source_ref, text} in descending score order.
        Empty query_vector or no vectorized pointers -> []."""
        if query_vector is None or len(query_vector) == 0:
            return []
        q = np.asarray(query_vector, dtype=float)
        qn = np.linalg.norm(q)
        if qn == 0:
            return []
        with get_pool(self.db_path).get() as conn:
            rows = conn.execute(
                "SELECT id, vector, source_kind, source_ref FROM context_pointers "
                "WHERE project = ? AND vector IS NOT NULL",
                (self.project,),
            ).fetchall()
        scored = []
        for pid, vector_json, source_kind, source_ref in rows:
            try:
                v = np.asarray(json.loads(vector_json), dtype=float)
            except (TypeError, ValueError):
                continue
            if v.shape != q.shape:
                continue
            vn = np.linalg.norm(v)
            if vn == 0:
                continue
            score = float(np.dot(q, v) / (qn * vn))
            scored.append((pid, score, source_kind, source_ref))
        scored.sort(key=lambda x: x[1], reverse=True)
        scored = scored[:top_k]
        out = []
        used_tokens = 0
        for pid, score, source_kind, source_ref in scored:
            text = self.resolve(pid)
            if not text:
                continue
            est_tokens = max(1, len(text) // 4)
            if used_tokens + est_tokens > budget_tokens:
                break
            used_tokens += est_tokens
            out.append({
                "id": pid,
                "score": score,
                "source_kind": source_kind,
                "source_ref": source_ref,
                "text": text,
            })
        return out

    def query_text(self, text, embed_fn, budget_tokens=4000, top_k=50):
        """Convenience wrapper: embed text with embed_fn (returns a list of
        floats) then delegate to query(). embed_fn failure or None -> []."""
        try:
            vec = embed_fn(text)
        except Exception:
            return []
        if vec is None:
            return []
        return self.query(vec, budget_tokens, top_k)

    def query_hybrid(self, query_text, query_vector, budget_tokens=4000, top_k=50,
                     candidate_k=150, vec_weight=0.5):
        """Hybrid retrieval: take vector-similarity candidates (up to candidate_k),
        resolve each to its raw span, score query_text lexically (BM25) over those
        spans, then fuse (vec_weight*vec_norm + (1-vec_weight)*bm25_norm) with
        min-max normalization of each signal to [0,1]. Pack the best up to
        budget_tokens (~4 chars/token). Returns a list of dicts
        {id, score, vec_score, bm25_score, source_kind, source_ref, text} in
        descending fused-score order. Empty query_vector -> BM25 only over ALL of
        the project's pointers (resolved). No pointers -> []."""
        candidates = []  # (id, vec_score, source_kind, source_ref)
        if query_vector is not None and len(query_vector) > 0:
            q = np.asarray(query_vector, dtype=float)
            qn = np.linalg.norm(q)
            if qn != 0:
                with get_pool(self.db_path).get() as conn:
                    rows = conn.execute(
                        "SELECT id, vector, source_kind, source_ref "
                        "FROM context_pointers "
                        "WHERE project = ? AND vector IS NOT NULL",
                        (self.project,),
                    ).fetchall()
                scored = []
                for pid, vector_json, source_kind, source_ref in rows:
                    try:
                        v = np.asarray(json.loads(vector_json), dtype=float)
                    except (TypeError, ValueError):
                        continue
                    if v.shape != q.shape:
                        continue
                    vn = np.linalg.norm(v)
                    if vn == 0:
                        continue
                    vec_score = float(np.dot(q, v) / (qn * vn))
                    scored.append((pid, vec_score, source_kind, source_ref))
                scored.sort(key=lambda x: x[1], reverse=True)
                candidates = scored[:candidate_k]
        if not candidates:
            candidates = [(p["id"], 0.0, p["source_kind"], p["source_ref"])
                          for p in self.pointers(self.project)]

        resolved = []  # (id, vec_score, source_kind, source_ref, text)
        for pid, vec_score, source_kind, source_ref in candidates:
            text = self.resolve(pid)
            if not text:
                continue
            resolved.append((pid, vec_score, source_kind, source_ref, text))
        if not resolved:
            return []

        bm25 = bm25_scores(query_text, [r[4] for r in resolved])
        # Raw clamped cosine for the vector signal and max-normalized BM25 keep the
        # RELATIVE margin between candidates. min-max would flatten 2 candidates to
        # 1 vs 0 on each axis, fusing both to exactly 0.5 at vec_weight=0.5 (a tie
        # the stable sort breaks toward the worse, vector-only winner -- an e2e bug).
        max_bm25 = max(bm25) if bm25 else 0.0

        items = []
        for i, (pid, vec_score, source_kind, source_ref, text) in enumerate(resolved):
            vec_clamped = max(0.0, vec_score)
            bm25_norm = bm25[i] / max_bm25 if max_bm25 > 0 else 0.0
            fused = vec_weight * vec_clamped + (1 - vec_weight) * bm25_norm
            items.append({
                "id": pid,
                "score": fused,
                "vec_score": vec_score,
                "bm25_score": bm25[i],
                "source_kind": source_kind,
                "source_ref": source_ref,
                "text": text,
            })
        items.sort(key=lambda d: d["score"], reverse=True)
        items = items[:top_k]

        out = []
        used_tokens = 0
        for it in items:
            est_tokens = max(1, len(it["text"]) // 4)
            if used_tokens + est_tokens > budget_tokens:
                break
            used_tokens += est_tokens
            out.append(it)
        return out

    def query_text_hybrid(self, query_text, embed_fn, budget_tokens=4000,
                          top_k=50, vec_weight=0.5):
        """Convenience wrapper: embed query_text with embed_fn then delegate to
        query_hybrid. embed_fn failure or None -> empty vector (falls to BM25)."""
        try:
            vec = embed_fn(query_text)
        except Exception:
            vec = []
        if vec is None:
            vec = []
        return self.query_hybrid(query_text, vec, budget_tokens=budget_tokens,
                                 top_k=top_k, vec_weight=vec_weight)

    def list_projects(self):
        """SELECT DISTINCT project FROM context_pointers (ignora self.project)."""
        with get_pool(self.db_path).get() as conn:
            rows = conn.execute(
                "SELECT DISTINCT project FROM context_pointers ORDER BY project"
            ).fetchall()
        return [r[0] for r in rows]

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

    def write_markdown(self, out_path, project=None):
        """Write the pointer index (NOT the full text) of `project` to out_path
        as an ASCII markdown file. Pointers are grouped by source_ref so the
        file reads as a map: which span of which source each pointer covers.
        Returns out_path."""
        proj = project if project is not None else self.project
        ptrs = self.pointers(proj)
        groups = {}
        for p in ptrs:
            groups.setdefault(p["source_ref"], []).append(p)
        lines = []
        lines.append("# Mapa de contexto: " + str(proj))
        lines.append("")
        lines.append(
            str(len(ptrs)) + " punteros, " + str(len(groups)) + " fuentes cubiertas"
        )
        lines.append("")
        for source_ref in sorted(groups.keys()):
            lines.append("## " + str(source_ref))
            for p in groups[source_ref]:
                cs = "" if p["char_start"] is None else str(p["char_start"])
                ce = "" if p["char_end"] is None else str(p["char_end"])
                summary = p["summary"] if p["summary"] is not None else ""
                lines.append(
                    "- [" + str(p["source_kind"]) + " " + cs + ":" + ce +
                    " | id " + str(p["id"]) + "] " + summary
                )
            lines.append("")
        Path(out_path).write_text("\n".join(lines), encoding="utf-8")
        return out_path
