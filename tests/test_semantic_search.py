"""
tests/test_semantic_search.py
==============================
6 tests for SemanticMemorySearch (TF-IDF over conversation history).
"""

from __future__ import annotations

import math
import sqlite3
import tempfile
import os
from unittest.mock import patch, MagicMock

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sms(db_path: str):
    """Instantiate SemanticMemorySearch bound to a temp DB."""
    from cognia.memory.semantic_search import SemanticMemorySearch
    return SemanticMemorySearch(db_path=db_path)


def _init_db(db_path: str) -> None:
    """Create chat_history table in a temp SQLite file."""
    con = sqlite3.connect(db_path)
    con.execute(
        "CREATE TABLE IF NOT EXISTS chat_history ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  session_id TEXT NOT NULL,"
        "  role TEXT NOT NULL,"
        "  content TEXT NOT NULL,"
        "  ts INTEGER NOT NULL DEFAULT 0"
        ")"
    )
    con.commit()
    con.close()


def _insert_rows(db_path: str, rows: list[tuple]) -> None:
    """Insert (session_id, role, content, ts) tuples."""
    con = sqlite3.connect(db_path)
    con.executemany(
        "INSERT INTO chat_history (session_id, role, content, ts) VALUES (?,?,?,?)",
        rows,
    )
    con.commit()
    con.close()


# ---------------------------------------------------------------------------
# Test 1: _tokenize removes stopwords
# ---------------------------------------------------------------------------

def test_tokenize_removes_stopwords():
    from cognia.memory.semantic_search import SemanticMemorySearch
    sms = SemanticMemorySearch.__new__(SemanticMemorySearch)
    tokens = sms._tokenize("el gato de la casa")
    # "el", "de", "la" are stopwords — should be removed
    assert "el" not in tokens
    assert "de" not in tokens
    assert "la" not in tokens
    # content words should remain
    assert "gato" in tokens
    assert "casa" in tokens


# ---------------------------------------------------------------------------
# Test 2: _tokenize returns non-empty list for normal text
# ---------------------------------------------------------------------------

def test_tokenize_non_empty_for_normal_text():
    from cognia.memory.semantic_search import SemanticMemorySearch
    sms = SemanticMemorySearch.__new__(SemanticMemorySearch)
    tokens = sms._tokenize("machine learning is great")
    assert len(tokens) > 0
    # "machine" and "learning" should survive (not stopwords, len >= 2)
    assert "machine" in tokens
    assert "learning" in tokens


# ---------------------------------------------------------------------------
# Test 3: _build_tfidf returns correct matrix shape
# ---------------------------------------------------------------------------

def test_build_tfidf_matrix_shape():
    from cognia.memory.semantic_search import SemanticMemorySearch
    sms = SemanticMemorySearch.__new__(SemanticMemorySearch)
    docs = [
        "python programming language",
        "machine learning algorithms",
        "neural network training",
    ]
    matrix, vocab = sms._build_tfidf(docs)
    n_docs = len(docs)
    v_size = len(vocab)

    assert matrix.shape == (n_docs, v_size), (
        f"Expected ({n_docs}, {v_size}), got {matrix.shape}"
    )
    assert v_size > 0, "Vocab should not be empty"
    assert matrix.dtype == np.float32


# ---------------------------------------------------------------------------
# Test 4: search returns empty list when no history
# ---------------------------------------------------------------------------

def test_search_empty_when_no_history(tmp_path):
    db_path = str(tmp_path / "chat.db")
    _init_db(db_path)

    # Patch get_pool to use our test DB
    from storage.db_pool import get_pool
    sms = _make_sms(db_path)
    results = sms.search("python programming", limit=5)
    assert results == []


# ---------------------------------------------------------------------------
# Test 5: search returns results sorted by score descending
# ---------------------------------------------------------------------------

def test_search_results_sorted_by_score_desc(tmp_path):
    db_path = str(tmp_path / "chat.db")
    _init_db(db_path)
    _insert_rows(db_path, [
        ("s1", "user", "I love python programming and coding", 1),
        ("s1", "assistant", "Python is a great programming language", 2),
        ("s1", "user", "What is the weather today", 3),
        ("s1", "assistant", "It might rain tomorrow", 4),
        ("s1", "user", "Explain neural networks in deep learning", 5),
    ])

    sms = _make_sms(db_path)
    results = sms.search("python programming language", limit=5)

    assert len(results) > 0, "Expected at least one result"
    # Verify descending order of scores
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True), (
        f"Scores not sorted descending: {scores}"
    )
    # Python-related messages should score higher than weather
    top_content = results[0]["content"].lower()
    assert "python" in top_content or "programming" in top_content, (
        f"Expected python-related content at top, got: {top_content}"
    )


# ---------------------------------------------------------------------------
# Test 6: cosine similarity of identical texts = 1.0
# ---------------------------------------------------------------------------

def test_cosine_similarity_identical_texts():
    from cognia.memory.semantic_search import SemanticMemorySearch
    sms = SemanticMemorySearch.__new__(SemanticMemorySearch)

    text = "deep neural network learning representation"
    docs = [text]
    query = text

    all_texts = docs + [query]
    matrix, vocab = sms._build_tfidf(all_texts)

    assert matrix.shape[1] > 0, "Vocab must be non-empty for identical texts"

    doc_vec = matrix[0]    # shape (vocab,)
    query_vec = matrix[1]  # shape (vocab,)

    # Cosine similarity between identical TF-IDF vectors should be 1.0
    sims = sms._cosine_similarity(query_vec, matrix[:1])
    assert abs(sims[0] - 1.0) < 1e-5, f"Expected ~1.0, got {sims[0]}"


# ---------------------------------------------------------------------------
# Test 7: tolera el schema del REPL (columna 'timestamp', no 'ts')
# ---------------------------------------------------------------------------

def _init_db_repl_schema(db_path: str) -> None:
    """chat_history con el schema del REPL (cognia_memory.db): 'timestamp TEXT', sin 'ts'."""
    con = sqlite3.connect(db_path)
    con.execute(
        "CREATE TABLE IF NOT EXISTS chat_history ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  timestamp TEXT NOT NULL,"
        "  role TEXT NOT NULL,"
        "  content TEXT NOT NULL,"
        "  session_id TEXT"
        ")"
    )
    con.commit()
    con.close()


def test_search_tolerates_repl_timestamp_schema(tmp_path):
    """Regresion (FASE 2a): chat_history con 'timestamp' (no 'ts') no debe romper
    search()/search_context(). Antes lanzaba OperationalError: no such column: ts."""
    db_path = str(tmp_path / "repl_chat.db")
    _init_db_repl_schema(db_path)
    con = sqlite3.connect(db_path)
    con.executemany(
        "INSERT INTO chat_history (timestamp, role, content, session_id) VALUES (?,?,?,?)",
        [
            ("2026-06-16T10:00:00", "user", "hablamos de shards y tensor parallel", "s1"),
            ("2026-06-16T10:01:00", "assistant", "los shards se reparten por la LAN", "s1"),
            ("2026-06-16T10:02:00", "user", "que clima hace hoy", "s1"),
        ],
    )
    con.commit()
    con.close()
    try:
        sms = _make_sms(db_path)
        results = sms.search("shards tensor parallel", limit=3)
        assert len(results) >= 1
        assert "shards" in results[0]["content"].lower()
        ctx = sms.search_context("shards", window=2)
        assert len(ctx) >= 1
    finally:
        from storage.db_pool import close_pool
        close_pool(db_path)
