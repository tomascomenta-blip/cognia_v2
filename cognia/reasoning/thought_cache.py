"""
cognia/reasoning/thought_cache.py — Thought-Chain Persistence (TCP)

Caches intermediate reasoning chains by question similarity so that repeated
or semantically close queries skip enrich_with_meta() entirely (~50-200 ms
saved per cache hit).

A thought chain is a dict with:
  question            : str
  reasoning_context   : str        from enrich_with_meta().context
  confidence          : float      from enrich_with_meta().confidence
  has_contradiction   : bool
  sub_questions       : list[str]  from enrich_with_meta().sub_questions
  hypothesis          : str | None from HypothesisModule (if generated)
  task_type           : str | None from classify_task()
  plan_steps          : list[str]  from plan_task() (if generated)
  timestamp           : float
  reuse_count         : int

Storage: own SQLite file (not main cognia DB) — explicitly allowed per CLAUDE.md
note for semantic_cache. Thread-safe via RLock.
Similarity: TF-IDF cosine, threshold 0.88 (slightly below response cache 0.92
because reasoning chains tolerate slightly more variation).
TTL: 3 days. Max: 300 entries.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import threading
import time
from collections import Counter
from contextlib import contextmanager
from typing import Optional

import numpy as np

# ── Stopwords (Spanish + English) — same set as semantic_cache, copied intentionally ──
_STOPWORDS = frozenset({
    "el", "la", "los", "las", "un", "una", "de", "del", "en", "a",
    "que", "y", "es", "se", "por", "con", "para", "como", "su", "lo",
    "the", "a", "an", "is", "are", "of", "in", "to", "and", "for",
    "that", "it", "with", "as", "at", "be", "this", "or", "on", "by",
})

_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE    = re.compile(r"\s+")


def _tokenize(text: str) -> list[str]:
    """Lowercase, strip punctuation, remove stopwords."""
    text = text.lower()
    text = _PUNCT_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    return [t for t in text.split() if t and t not in _STOPWORDS]


def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


_DDL = """
CREATE TABLE IF NOT EXISTS thought_chains (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    question_normalized TEXT    NOT NULL,
    question_tokens     TEXT    NOT NULL,
    chain_json          TEXT    NOT NULL,
    similarity_hits     INTEGER NOT NULL DEFAULT 0,
    timestamp           REAL    NOT NULL
)
"""


class ThoughtCache:
    THRESHOLD   = 0.88
    TTL_DAYS    = 3
    MAX_ENTRIES = 300

    def __init__(self, db_path: str = "cognia_thought_cache.db") -> None:
        self._db_path = db_path
        self._lock    = threading.RLock()
        # In-memory TF-IDF vocabulary
        self._vocab: dict[str, int] = {}
        self._idf:   Optional[np.ndarray] = None
        self._vocab_dirty = True
        self._init_db()

    # ── DB helpers ────────────────────────────────────────────────────────

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute(_DDL)

    # ── TF-IDF helpers ────────────────────────────────────────────────────

    def _rebuild_vocab(self, conn) -> None:
        rows = conn.execute(
            "SELECT question_tokens FROM thought_chains"
        ).fetchall()
        if not rows:
            self._vocab = {}
            self._idf   = None
            return

        doc_tokens: list[list[str]] = []
        for r in rows:
            try:
                toks = json.loads(r[0])
                if isinstance(toks, list):
                    doc_tokens.append(toks)
            except Exception:
                pass

        if not doc_tokens:
            self._vocab = {}
            self._idf   = None
            return

        freq: Counter = Counter()
        for toks in doc_tokens:
            freq.update(set(toks))

        all_tokens = sorted(set(t for toks in doc_tokens for t in toks),
                            key=lambda t: -freq[t])[:2000]
        self._vocab = {t: i for i, t in enumerate(all_tokens)}

        N = len(doc_tokens)
        idf = np.ones(len(self._vocab), dtype=np.float32)
        for tok, idx in self._vocab.items():
            df = freq[tok]
            idf[idx] = math.log((N + 1) / (df + 1)) + 1.0
        self._idf = idf
        self._vocab_dirty = False

    def _tfidf_vector(self, tokens: list[str]) -> Optional[np.ndarray]:
        if not self._vocab or self._idf is None:
            return None
        tf: Counter = Counter(tokens)
        total = len(tokens) or 1
        vec = np.zeros(len(self._vocab), dtype=np.float32)
        for tok, cnt in tf.items():
            idx = self._vocab.get(tok)
            if idx is not None:
                vec[idx] = (cnt / total) * self._idf[idx]
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec /= norm
        return vec

    def _bootstrap_vocab(self, tokens: list[str]) -> None:
        """Build a minimal vocab from a single question when cache was empty."""
        self._vocab = {t: i for i, t in enumerate(tokens[:2000])}
        self._idf   = np.ones(len(self._vocab), dtype=np.float32)
        self._vocab_dirty = False

    # ── Public API ────────────────────────────────────────────────────────

    def lookup(self, question: str) -> Optional[dict]:
        """
        Return the cached thought chain if a similar question is found.
        Updates similarity_hits on hit. Returns None on miss or error.
        """
        with self._lock:
            try:
                tokens = _tokenize(question)
                if not tokens:
                    return None

                with self._conn() as conn:
                    if self._vocab_dirty:
                        self._rebuild_vocab(conn)

                    qvec = self._tfidf_vector(tokens)
                    if qvec is None:
                        return None

                    now  = time.time()
                    ttl  = self.TTL_DAYS * 86400.0
                    rows = conn.execute(
                        "SELECT id, question_tokens, chain_json, timestamp "
                        "FROM thought_chains"
                    ).fetchall()

                    best_sim  = -1.0
                    best_id   = None
                    best_chain: Optional[dict] = None

                    for row in rows:
                        if now - row["timestamp"] > ttl:
                            continue
                        try:
                            row_toks = json.loads(row["question_tokens"])
                            rvec = self._tfidf_vector(row_toks)
                        except Exception:
                            continue
                        if rvec is None or rvec.shape != qvec.shape:
                            continue
                        sim = _cosine_sim(qvec, rvec)
                        if sim > best_sim:
                            best_sim   = sim
                            best_id    = row["id"]
                            best_chain = json.loads(row["chain_json"])

                    if best_sim >= self.THRESHOLD and best_id is not None:
                        conn.execute(
                            "UPDATE thought_chains "
                            "SET similarity_hits = similarity_hits + 1 "
                            "WHERE id = ?",
                            (best_id,),
                        )
                        return best_chain

                return None
            except Exception:
                return None

    def store(self, question: str, chain: dict) -> None:
        """
        Store a thought chain. chain must have at minimum:
          reasoning_context (str) and confidence (float).
        """
        with self._lock:
            try:
                tokens = _tokenize(question)
                if not tokens:
                    return
                if "reasoning_context" not in chain or "confidence" not in chain:
                    return

                full_chain = {
                    "question":          question,
                    "reasoning_context": chain.get("reasoning_context", ""),
                    "confidence":        float(chain.get("confidence", 0.5)),
                    "has_contradiction": bool(chain.get("has_contradiction", False)),
                    "sub_questions":     list(chain.get("sub_questions", [])),
                    "hypothesis":        chain.get("hypothesis"),
                    "task_type":         chain.get("task_type"),
                    "plan_steps":        list(chain.get("plan_steps", [])),
                    "timestamp":         time.time(),
                    "reuse_count":       0,
                }

                with self._conn() as conn:
                    self._vocab_dirty = True
                    self._rebuild_vocab(conn)

                    if self._vocab is None or not self._vocab:
                        self._bootstrap_vocab(tokens)

                    norm_q = " ".join(tokens)
                    toks_json  = json.dumps(tokens)
                    chain_json = json.dumps(full_chain)

                    conn.execute(
                        "INSERT INTO thought_chains "
                        "(question_normalized, question_tokens, chain_json, "
                        " similarity_hits, timestamp) "
                        "VALUES (?, ?, ?, 0, ?)",
                        (norm_q, toks_json, chain_json, time.time()),
                    )

                    count = conn.execute(
                        "SELECT COUNT(*) FROM thought_chains"
                    ).fetchone()[0]
                    if count > self.MAX_ENTRIES:
                        # prune oldest 20 to amortize I/O
                        conn.execute(
                            "DELETE FROM thought_chains WHERE id IN "
                            "(SELECT id FROM thought_chains "
                            " ORDER BY timestamp ASC LIMIT 20)"
                        )
                        self._vocab_dirty = True

            except Exception:
                pass

    def stats(self) -> dict:
        """{'total': int, 'hits': int, 'avg_reuse': float}"""
        with self._lock:
            try:
                with self._conn() as conn:
                    row = conn.execute(
                        "SELECT COUNT(*), COALESCE(SUM(similarity_hits), 0) "
                        "FROM thought_chains"
                    ).fetchone()
                    total, total_hits = int(row[0]), int(row[1])
                    avg_reuse = round(total_hits / total, 4) if total > 0 else 0.0
                    return {
                        "total":     total,
                        "hits":      total_hits,
                        "avg_reuse": avg_reuse,
                    }
            except Exception:
                return {"total": 0, "hits": 0, "avg_reuse": 0.0}
