"""
tests/test_knowledge_synthesizer.py
=====================================
Tests for KnowledgeSynthesizer — 5 tests covering empty/populated paths.
"""
from __future__ import annotations

import os
import tempfile

import pytest


def _make_synthesizer_with_dbs(chat_db: str, kg_db: str):
    """Create a KnowledgeSynthesizer with injected db paths."""
    import cognia.synthesis.knowledge_synthesizer as ks_mod
    ks_mod._CHAT_DB = chat_db
    ks_mod._KG_DB = kg_db
    from cognia.synthesis.knowledge_synthesizer import KnowledgeSynthesizer
    return KnowledgeSynthesizer()


def _init_chat_db(db_path: str) -> None:
    from storage.db_pool import get_pool
    with get_pool(db_path).get() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS smart_notes ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  session_id TEXT,"
            "  content TEXT NOT NULL,"
            "  note_type TEXT,"
            "  source TEXT,"
            "  pinned INTEGER DEFAULT 0,"
            "  ts INTEGER DEFAULT 0"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS chat_history ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  session_id TEXT NOT NULL,"
            "  role TEXT NOT NULL,"
            "  content TEXT NOT NULL,"
            "  ts INTEGER NOT NULL DEFAULT 0"
            ")"
        )


def _init_kg_db(db_path: str) -> None:
    from storage.db_pool import get_pool
    with get_pool(db_path).get() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS knowledge_graph ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  subject TEXT NOT NULL,"
            "  predicate TEXT NOT NULL,"
            "  object TEXT NOT NULL,"
            "  weight REAL DEFAULT 1.0,"
            "  UNIQUE(subject, predicate, object)"
            ")"
        )


def _close_dbs(*paths: str) -> None:
    """Release pool connections so Windows can delete temp files."""
    from storage.db_pool import close_pool
    for p in paths:
        try:
            close_pool(p)
        except Exception:
            pass


# ── Test 1: _extract_relevant_notes returns a list (even if empty) ─────

def test_extract_relevant_notes_returns_list():
    with tempfile.TemporaryDirectory() as tmpdir:
        chat_db = os.path.join(tmpdir, "chat.db")
        kg_db = os.path.join(tmpdir, "kg.db")
        _init_chat_db(chat_db)
        _init_kg_db(kg_db)
        s = _make_synthesizer_with_dbs(chat_db, kg_db)
        try:
            result = s._extract_relevant_notes("python")
            assert isinstance(result, list)
        finally:
            _close_dbs(chat_db, kg_db)


# ── Test 2: _extract_kg_facts returns a list ───────────────────────────

def test_extract_kg_facts_returns_list():
    with tempfile.TemporaryDirectory() as tmpdir:
        chat_db = os.path.join(tmpdir, "chat.db")
        kg_db = os.path.join(tmpdir, "kg.db")
        _init_chat_db(chat_db)
        _init_kg_db(kg_db)
        s = _make_synthesizer_with_dbs(chat_db, kg_db)
        try:
            result = s._extract_kg_facts("python")
            assert isinstance(result, list)
        finally:
            _close_dbs(chat_db, kg_db)


# ── Test 3: synthesize returns dict with required keys ─────────────────

def test_synthesize_returns_required_keys():
    with tempfile.TemporaryDirectory() as tmpdir:
        chat_db = os.path.join(tmpdir, "chat.db")
        kg_db = os.path.join(tmpdir, "kg.db")
        _init_chat_db(chat_db)
        _init_kg_db(kg_db)
        s = _make_synthesizer_with_dbs(chat_db, kg_db)
        try:
            result = s.synthesize("python")
            required = {"topic", "notes_count", "kg_facts_count", "chat_refs_count", "synthesis", "sources"}
            assert required.issubset(result.keys())
        finally:
            _close_dbs(chat_db, kg_db)


# ── Test 4: synthesize with no data returns empty sections gracefully ──

def test_synthesize_no_data_graceful():
    with tempfile.TemporaryDirectory() as tmpdir:
        chat_db = os.path.join(tmpdir, "chat.db")
        kg_db = os.path.join(tmpdir, "kg.db")
        _init_chat_db(chat_db)
        _init_kg_db(kg_db)
        s = _make_synthesizer_with_dbs(chat_db, kg_db)
        try:
            result = s.synthesize("nonexistenttopicxyz")
            assert result["notes_count"] == 0
            assert result["kg_facts_count"] == 0
            assert result["chat_refs_count"] == 0
            assert result["sources"] == []
            assert isinstance(result["synthesis"], str)
        finally:
            _close_dbs(chat_db, kg_db)


# ── Test 5: synthesis string contains topic name ───────────────────────

def test_synthesis_string_contains_topic():
    with tempfile.TemporaryDirectory() as tmpdir:
        chat_db = os.path.join(tmpdir, "chat.db")
        kg_db = os.path.join(tmpdir, "kg.db")
        _init_chat_db(chat_db)
        _init_kg_db(kg_db)

        topic = "python"

        from storage.db_pool import get_pool
        with get_pool(chat_db).get() as conn:
            conn.execute(
                "INSERT INTO smart_notes (session_id, content, note_type, source, ts) VALUES (?,?,?,?,?)",
                ("s1", "python es un lenguaje de programacion", "fact", "test", 0),
            )
            conn.execute(
                "INSERT INTO chat_history (session_id, role, content, ts) VALUES (?,?,?,?)",
                ("s1", "assistant", "python tiene tipado dinamico y es muy popular", 0),
            )
        with get_pool(kg_db).get() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO knowledge_graph (subject, predicate, object) VALUES (?,?,?)",
                ("python", "is_a", "lenguaje"),
            )

        s = _make_synthesizer_with_dbs(chat_db, kg_db)
        try:
            result = s.synthesize(topic)
            assert topic in result["synthesis"]
            assert (
                result["notes_count"] >= 1
                or result["kg_facts_count"] >= 1
                or result["chat_refs_count"] >= 1
            )
        finally:
            _close_dbs(chat_db, kg_db)
