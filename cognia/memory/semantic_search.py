"""
cognia/memory/semantic_search.py
=================================
Pure numpy + stdlib TF-IDF semantic search over conversation history.
No external ML libraries required.

Reads chat_history from the DB pool (never sqlite3.connect() directly).
Index is built in-memory on each search call — no persistent table needed.
"""

from __future__ import annotations

import math
import re
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    pass

_STOPWORDS: frozenset[str] = frozenset({
    "el", "la", "los", "las", "de", "que", "en", "y", "a", "es",
    "un", "una", "the", "is", "an", "of", "to", "and", "or",
    "se", "su", "con", "por", "para", "como", "pero", "mas", "si",
    "no", "me",
})


class SemanticMemorySearch:
    """TF-IDF semantic search over chat_history using pure numpy."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    # ------------------------------------------------------------------
    # Tokenization
    # ------------------------------------------------------------------

    def _tokenize(self, text: str) -> list[str]:
        """Lowercase + split on non-alphanumeric; filter short tokens and stopwords."""
        tokens = re.findall(r"\w+", text.lower())
        return [t for t in tokens if len(t) >= 2 and t not in _STOPWORDS]

    # ------------------------------------------------------------------
    # TF-IDF construction
    # ------------------------------------------------------------------

    def _build_tfidf(
        self, docs: list[str]
    ) -> tuple[np.ndarray, list[str]]:
        """
        Build a TF-IDF matrix from a list of document strings.

        Returns:
            matrix  : np.ndarray of shape (n_docs, vocab_size), float32
            vocab   : list of terms (column labels)
        """
        if not docs:
            return np.zeros((0, 0), dtype=np.float32), []

        tokenized: list[list[str]] = [self._tokenize(doc) for doc in docs]

        # Build vocabulary
        vocab_set: set[str] = set()
        for tokens in tokenized:
            vocab_set.update(tokens)
        vocab: list[str] = sorted(vocab_set)
        if not vocab:
            return np.zeros((len(docs), 0), dtype=np.float32), []

        term_index: dict[str, int] = {term: i for i, term in enumerate(vocab)}
        n_docs = len(docs)
        v_size = len(vocab)

        matrix = np.zeros((n_docs, v_size), dtype=np.float32)

        # Compute TF
        for i, tokens in enumerate(tokenized):
            total = len(tokens)
            if total == 0:
                continue
            for token in tokens:
                j = term_index.get(token)
                if j is not None:
                    matrix[i, j] += 1.0
            matrix[i] /= total  # TF = count / total_tokens

        # Compute IDF  (log((N+1)/(df+1))+1) — sklearn-style smooth
        df = (matrix > 0).sum(axis=0).astype(np.float32)  # (v_size,)
        idf = np.log((n_docs + 1.0) / (df + 1.0)) + 1.0   # (v_size,)

        matrix = matrix * idf  # broadcast: (n_docs, v_size) * (v_size,)
        return matrix.astype(np.float32), vocab

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ts_column(self, conn) -> str:
        """Nombre de la columna de tiempo en chat_history: 'ts' (schema desktop/test)
        o 'timestamp' (schema REPL en cognia_memory.db). Permite a la misma clase
        operar sobre ambos esquemas sin romper (la columna se aliasa luego AS ts).
        Default 'ts'."""
        cols = {row[1] for row in conn.execute("PRAGMA table_info(chat_history)").fetchall()}
        if "ts" in cols:
            return "ts"
        if "timestamp" in cols:
            return "timestamp"
        return "ts"

    def _load_history(self, limit: int = 200) -> list[dict]:
        """Load last `limit` rows from chat_history ordered by id asc."""
        from storage.db_pool import get_pool
        with get_pool(self._db_path).get() as conn:
            tscol = self._ts_column(conn)   # 'ts' o 'timestamp' (allowlist -> sin injection)
            rows = conn.execute(
                f"SELECT id, session_id, role, content, {tscol} AS ts "
                "FROM chat_history ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        # Return in chronological order (oldest first)
        rows = list(reversed(rows))
        return [
            {
                "id": r[0],
                "session_id": r[1],
                "role": r[2],
                "content": r[3],
                "ts": r[4],
            }
            for r in rows
        ]

    @staticmethod
    def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> np.ndarray:
        """Compute cosine similarity between vector a (1-D) and each row of b (2-D).
        Returns 1-D array of shape (n_rows,).
        """
        norm_a = np.linalg.norm(a)
        if norm_a == 0.0:
            return np.zeros(b.shape[0], dtype=np.float32)
        norms_b = np.linalg.norm(b, axis=1)
        # Avoid division by zero for zero-vectors in b
        safe_norms = np.where(norms_b == 0.0, 1.0, norms_b)
        sims = (b @ a) / (norm_a * safe_norms)
        sims = np.where(norms_b == 0.0, 0.0, sims)
        return sims.astype(np.float32)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        limit: int = 5,
        role: str = "all",
    ) -> list[dict]:
        """
        Search conversation history using TF-IDF cosine similarity.

        Returns top-`limit` results as dicts with keys:
            id, session_id, role, content, ts, score
        sorted by score descending.
        """
        rows = self._load_history(limit=200)
        if not rows:
            return []

        if role != "all":
            rows = [r for r in rows if r["role"] == role]
        if not rows:
            return []

        docs = [r["content"] for r in rows]

        # Build TF-IDF matrix over all docs + query together, then split
        all_texts = docs + [query]
        matrix, vocab = self._build_tfidf(all_texts)

        if matrix.shape[1] == 0:
            # No vocabulary (e.g. all stopwords)
            return []

        doc_matrix = matrix[: len(docs)]   # (n_docs, vocab)
        query_vec = matrix[len(docs)]       # (vocab,)

        scores = self._cosine_similarity(query_vec, doc_matrix)

        # Pair rows with scores, sort descending
        indexed = sorted(
            zip(scores.tolist(), rows), key=lambda x: x[0], reverse=True
        )
        top = indexed[:limit]

        results = []
        for score, row in top:
            results.append({**row, "score": float(score)})
        return results

    def search_context(
        self,
        query: str,
        window: int = 3,
    ) -> list[dict]:
        """
        Find the best matching message and return surrounding conversation window.

        Fetches the top-1 result from search(), then retrieves `window` messages
        before and after (within the same session) by id proximity (monotono, asi
        funciona igual con ts INTEGER o timestamp TEXT).
        Returns the conversation snippet sorted by id asc.
        """
        top = self.search(query, limit=1)
        if not top:
            return []

        best = top[0]
        session_id = best["session_id"]
        center_id = best["id"]   # ventana por id (monotono) -> independiente del tipo de ts

        from storage.db_pool import get_pool
        with get_pool(self._db_path).get() as conn:
            tscol = self._ts_column(conn)
            # Fetch window messages before + center
            before = conn.execute(
                f"SELECT id, session_id, role, content, {tscol} AS ts "
                "FROM chat_history "
                "WHERE session_id = ? AND id <= ? "
                "ORDER BY id DESC LIMIT ?",
                (session_id, center_id, window + 1),
            ).fetchall()
            # Fetch window messages after
            after = conn.execute(
                f"SELECT id, session_id, role, content, {tscol} AS ts "
                "FROM chat_history "
                "WHERE session_id = ? AND id > ? "
                "ORDER BY id ASC LIMIT ?",
                (session_id, center_id, window),
            ).fetchall()

        def _to_dict(r: tuple) -> dict:
            return {
                "id": r[0],
                "session_id": r[1],
                "role": r[2],
                "content": r[3],
                "ts": r[4],
            }

        snippet = [_to_dict(r) for r in reversed(before)] + [_to_dict(r) for r in after]
        # Deduplicate by id preserving order
        seen: set[int] = set()
        unique: list[dict] = []
        for item in snippet:
            if item["id"] not in seen:
                seen.add(item["id"])
                unique.append(item)

        unique.sort(key=lambda x: x["id"])
        return unique
