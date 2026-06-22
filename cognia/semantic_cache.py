"""
cognia/semantic_cache.py — Semantic Response Cache (SRC)
Caches AI responses keyed by TF-IDF cosine similarity so repeated or
semantically close queries are answered in <5 ms instead of ~5 s.
"""

from __future__ import annotations

import io
import math
import re
import threading
import time
from collections import Counter
from typing import Optional

import numpy as np

# Spanish + English stopwords — fixed set, no external dep
_STOPWORDS = frozenset({
    "el", "la", "los", "las", "un", "una", "de", "del", "en", "a",
    "que", "y", "es", "se", "por", "con", "para", "como", "su", "lo",
    "the", "a", "an", "is", "are", "of", "in", "to", "and", "for",
    "that", "it", "with", "as", "at", "be", "this", "or", "on", "by",
})

_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE    = re.compile(r"\s+")


def _normalize(text: str) -> list[str]:
    text = text.lower()
    text = _PUNCT_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    return [t for t in text.split() if t and t not in _STOPWORDS]


def _serialize(arr: np.ndarray) -> bytes:
    buf = io.BytesIO()
    np.save(buf, arr)
    return buf.getvalue()


def _deserialize(blob: bytes) -> np.ndarray:
    buf = io.BytesIO(blob)
    return np.load(buf, allow_pickle=False)


def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


_DDL = """
CREATE TABLE IF NOT EXISTS semantic_cache (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    question_norm   TEXT    NOT NULL,
    tfidf_vector    BLOB    NOT NULL,
    response        TEXT    NOT NULL,
    model           TEXT    NOT NULL DEFAULT '',
    timestamp       REAL    NOT NULL,
    hits            INTEGER NOT NULL DEFAULT 0
)
"""


class SemanticResponseCache:
    def __init__(
        self,
        db_pool,
        ttl_days: float = 7.0,
        sim_threshold: float = 0.92,
        max_entries: int = 500,
    ) -> None:
        self._pool          = db_pool
        self._ttl           = ttl_days * 86400.0
        self._threshold     = sim_threshold
        self._max_entries   = max_entries
        self._lock          = threading.RLock()
        # In-memory vocabulary built from cached questions
        self._vocab: dict[str, int] = {}   # token -> index
        self._idf:  Optional[np.ndarray] = None
        self._vocab_dirty   = True         # rebuild on next vectorize call
        self._init_table()

    # ── private ────────────────────────────────────────────────────────

    def _init_table(self) -> None:
        with self._pool.get() as conn:
            conn.execute(_DDL)

    def _rebuild_vocab(self, conn) -> None:
        """Rebuild TF-IDF vocabulary from all cached question_norm strings."""
        rows = conn.execute(
            "SELECT question_norm FROM semantic_cache"
        ).fetchall()
        if not rows:
            self._vocab = {}
            self._idf   = None
            return

        doc_tokens = [r[0].split() for r in rows]
        # collect token universe
        all_tokens: set[str] = set()
        for toks in doc_tokens:
            all_tokens.update(toks)

        # cap vocabulary size
        freq: Counter = Counter()
        for toks in doc_tokens:
            freq.update(set(toks))

        top = sorted(all_tokens, key=lambda t: -freq[t])[:2000]
        self._vocab = {t: i for i, t in enumerate(top)}

        # IDF = log((N+1) / (df+1)) + 1  (smooth)
        N = len(doc_tokens)
        idf = np.ones(len(self._vocab), dtype=np.float32)
        for tok, idx in self._vocab.items():
            df = freq[tok]
            idf[idx] = math.log((N + 1) / (df + 1)) + 1.0
        self._idf = idf
        self._vocab_dirty = False

    def _tfidf_vector(self, tokens: list[str]) -> Optional[np.ndarray]:
        """Compute TF-IDF vector for a token list using current vocab."""
        if not self._vocab or self._idf is None:
            return None

        tf_counts: Counter = Counter(tokens)
        total = len(tokens) or 1
        vec = np.zeros(len(self._vocab), dtype=np.float32)
        for tok, cnt in tf_counts.items():
            idx = self._vocab.get(tok)
            if idx is not None:
                vec[idx] = (cnt / total) * self._idf[idx]

        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec /= norm
        return vec

    def _entry_count(self, conn) -> int:
        return conn.execute("SELECT COUNT(*) FROM semantic_cache").fetchone()[0]

    def _prune_oldest(self, conn, n: int = 50) -> None:
        conn.execute(
            "DELETE FROM semantic_cache WHERE id IN "
            "(SELECT id FROM semantic_cache ORDER BY timestamp ASC LIMIT ?)",
            (n,),
        )

    # ── public API ─────────────────────────────────────────────────────

    def lookup(self, question: str) -> Optional[str]:
        with self._lock:
            try:
                tokens = _normalize(question)
                if not tokens:
                    return None

                with self._pool.get() as conn:
                    if self._vocab_dirty:
                        self._rebuild_vocab(conn)

                    qvec = self._tfidf_vector(tokens)
                    if qvec is None:
                        return None

                    now = time.time()
                    rows = conn.execute(
                        "SELECT id, question_norm, response, timestamp "
                        "FROM semantic_cache"
                    ).fetchall()

                    best_sim  = -1.0
                    best_id   = None
                    best_resp = None

                    for row_id, question_norm, response, ts in rows:
                        # skip expired entries
                        if now - ts > self._ttl:
                            continue
                        # Recompute the candidate vector from its stored tokens
                        # against the CURRENT vocab. The persisted tfidf_vector blob
                        # is computed against the vocab snapshot at store() time, but
                        # the vocab drifts (grows + re-orders by frequency) as new
                        # questions are cached, so a stale blob is in a different basis
                        # than qvec — comparing them silently yields garbage similarity
                        # (or a shape mismatch that skips the entry). Recomputing from
                        # tokens keeps both vectors in the same basis (same fix as
                        # thought_cache.py, which stores tokens for this reason).
                        cvec = self._tfidf_vector(question_norm.split())
                        if cvec is None or cvec.shape != qvec.shape:
                            continue
                        sim = _cosine_sim(qvec, cvec)
                        if sim > best_sim:
                            best_sim  = sim
                            best_id   = row_id
                            best_resp = response

                    if best_sim >= self._threshold and best_id is not None:
                        conn.execute(
                            "UPDATE semantic_cache SET hits = hits + 1 WHERE id = ?",
                            (best_id,),
                        )
                        return best_resp

                return None
            except Exception:
                return None

    def store(self, question: str, response: str, model: str = "") -> None:
        with self._lock:
            try:
                tokens = _normalize(question)
                if not tokens:
                    return

                with self._pool.get() as conn:
                    self._vocab_dirty = True
                    self._rebuild_vocab(conn)

                    vec = self._tfidf_vector(tokens)
                    if vec is None:
                        # vocab still empty — build a minimal one from this question
                        self._vocab = {t: i for i, t in enumerate(tokens[:2000])}
                        N = 1
                        idf = np.ones(len(self._vocab), dtype=np.float32)
                        self._idf = idf
                        vec = self._tfidf_vector(tokens)
                        if vec is None:
                            return

                    blob = _serialize(vec)
                    norm_text = " ".join(tokens)
                    conn.execute(
                        "INSERT INTO semantic_cache "
                        "(question_norm, tfidf_vector, response, model, timestamp, hits) "
                        "VALUES (?, ?, ?, ?, ?, 0)",
                        (norm_text, blob, response, model, time.time()),
                    )

                    if self._entry_count(conn) > self._max_entries:
                        self._prune_oldest(conn)
                        self._vocab_dirty = True
            except Exception:
                pass

    def stats(self) -> dict:
        with self._lock:
            try:
                with self._pool.get() as conn:
                    row = conn.execute(
                        "SELECT COUNT(*), COALESCE(SUM(hits), 0) FROM semantic_cache"
                    ).fetchone()
                    entries, total_hits = row
                    # hit_rate = hits / (hits + entries) as a proxy
                    denom = total_hits + entries
                    hit_rate = total_hits / denom if denom > 0 else 0.0
                    return {
                        "entries":    int(entries),
                        "total_hits": int(total_hits),
                        "hit_rate":   round(hit_rate, 4),
                    }
            except Exception:
                return {"entries": 0, "total_hits": 0, "hit_rate": 0.0}
