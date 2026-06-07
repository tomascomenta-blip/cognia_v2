"""
tests/test_session_warm_starter.py
===================================
18+ unit tests for Phase 62 -- SessionWarmStarter (SWS).

Uses temp DB files and a mock KG to avoid hitting production data.
"""

import os
import sqlite3
import tempfile

import pytest

from cognia.context.session_warm_starter import SessionWarmStarter


# ── Helpers ───────────────────────────────────────────────────────────


class MockKG:
    """Minimal mock for KnowledgeGraph."""

    def __init__(self, facts=None, raise_on_call=False):
        self._facts = facts or []
        self._raise = raise_on_call

    def get_facts(self, concept):
        if self._raise:
            raise RuntimeError("KG unavailable")
        return self._facts


class MockConsolidator:
    """Minimal mock for LongTermConsolidator."""

    def __init__(self, summary="", raise_on_call=False):
        self._summary = summary
        self._raise = raise_on_call

    def get_summary(self, user_id):
        if self._raise:
            raise RuntimeError("Consolidator unavailable")
        return self._summary


def _make_db_with_gaps(topics: list) -> str:
    """Create a temp SQLite DB with knowledge_gaps table and given unresolved topics."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE knowledge_gaps ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "topic TEXT NOT NULL,"
        "question TEXT NOT NULL,"
        "quality_score REAL NOT NULL,"
        "timestamp REAL NOT NULL,"
        "resolved INTEGER DEFAULT 0)"
    )
    import time
    for i, topic in enumerate(topics):
        conn.execute(
            "INSERT INTO knowledge_gaps (topic, question, quality_score, timestamp, resolved) "
            "VALUES (?, ?, ?, ?, 0)",
            (topic, f"What is {topic}?", 0.2, time.time() - i),
        )
    conn.commit()
    conn.close()
    return path


def _make_db_no_gaps_table() -> str:
    """Create a temp SQLite DB WITHOUT knowledge_gaps table."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE dummy (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    return path


def _three_facts(weight=1.0):
    """Return 3 user facts with given weight."""
    return [
        {"subject": "user", "predicate": "is_a", "object": "developer", "weight": weight},
        {"subject": "user", "predicate": "has_property", "object": "python", "weight": weight},
        {"subject": "user", "predicate": "located_in", "object": "barcelona", "weight": weight},
    ]


# ── Tests ──────────────────────────────────────────────────────────────


class TestBuildBriefingReturnEmpty:

    def test_returns_empty_with_zero_facts(self, tmp_path):
        kg = MockKG(facts=[])
        sws = SessionWarmStarter(kg, str(tmp_path / "db.db"))
        assert sws.build_briefing("s1") == ""

    def test_returns_empty_with_one_fact(self, tmp_path):
        kg = MockKG(facts=[{"subject": "user", "predicate": "is_a", "object": "dev", "weight": 1.0}])
        sws = SessionWarmStarter(kg, str(tmp_path / "db.db"))
        assert sws.build_briefing("s1") == ""

    def test_returns_empty_with_two_facts(self, tmp_path):
        facts = _three_facts()[:2]
        kg = MockKG(facts=facts)
        sws = SessionWarmStarter(kg, str(tmp_path / "db.db"))
        assert sws.build_briefing("s1") == ""

    def test_returns_empty_when_all_facts_low_weight(self, tmp_path):
        """All facts below 0.5 threshold -> returns empty."""
        facts = _three_facts(weight=0.3)
        kg = MockKG(facts=facts)
        sws = SessionWarmStarter(kg, str(tmp_path / "db.db"))
        assert sws.build_briefing("s1") == ""

    def test_returns_empty_when_kg_raises(self, tmp_path):
        """KG failure -> fail safe, return empty."""
        kg = MockKG(raise_on_call=True)
        sws = SessionWarmStarter(kg, str(tmp_path / "db.db"))
        assert sws.build_briefing("s1") == ""

    def test_empty_kg_no_crash(self, tmp_path):
        """Empty KG -> returns '' and no exception."""
        kg = MockKG(facts=[])
        sws = SessionWarmStarter(kg, str(tmp_path / "db.db"))
        result = sws.build_briefing("s1")
        assert result == ""


class TestBuildBriefingContent:

    def test_returns_nonempty_with_three_facts(self, tmp_path):
        kg = MockKG(facts=_three_facts())
        db = _make_db_no_gaps_table()
        sws = SessionWarmStarter(kg, db)
        result = sws.build_briefing("s1")
        assert result != ""

    def test_starts_with_context_prefix(self, tmp_path):
        kg = MockKG(facts=_three_facts())
        db = _make_db_no_gaps_table()
        sws = SessionWarmStarter(kg, db)
        result = sws.build_briefing("s1")
        assert result.startswith("Context: ")

    def test_output_within_400_chars(self, tmp_path):
        kg = MockKG(facts=_three_facts())
        db = _make_db_with_gaps(["machine learning", "neural networks"])
        sws = SessionWarmStarter(kg, db)
        result = sws.build_briefing("s1")
        assert len(result) <= 400

    def test_user_facts_formatted_with_user_prefix(self, tmp_path):
        kg = MockKG(facts=_three_facts())
        db = _make_db_no_gaps_table()
        sws = SessionWarmStarter(kg, db)
        result = sws.build_briefing("s1")
        assert "User: " in result

    def test_low_weight_facts_filtered_out(self, tmp_path):
        """Only facts >= 0.5 should appear. Mix high and low."""
        facts = [
            {"subject": "user", "predicate": "is_a", "object": "developer", "weight": 1.0},
            {"subject": "user", "predicate": "is_a", "object": "gamer", "weight": 0.4},  # filtered
            {"subject": "user", "predicate": "has_property", "object": "python", "weight": 0.8},
            {"subject": "user", "predicate": "located_in", "object": "madrid", "weight": 0.9},
        ]
        kg = MockKG(facts=facts)
        db = _make_db_no_gaps_table()
        sws = SessionWarmStarter(kg, db)
        result = sws.build_briefing("s1")
        assert "gamer" not in result

    def test_sorted_by_weight_highest_first(self, tmp_path):
        """Highest weight fact should appear first in user facts section."""
        facts = [
            {"subject": "user", "predicate": "is_a", "object": "aaa", "weight": 0.6},
            {"subject": "user", "predicate": "is_a", "object": "bbb", "weight": 0.9},
            {"subject": "user", "predicate": "is_a", "object": "ccc", "weight": 0.7},
        ]
        kg = MockKG(facts=facts)
        db = _make_db_no_gaps_table()
        sws = SessionWarmStarter(kg, db)
        result = sws.build_briefing("s1")
        pos_bbb = result.find("bbb")
        pos_ccc = result.find("ccc")
        pos_aaa = result.find("aaa")
        assert pos_bbb < pos_ccc < pos_aaa

    def test_sections_separated_by_pipe(self, tmp_path):
        """With gaps present, sections should be joined with ' | '."""
        kg = MockKG(facts=_three_facts())
        db = _make_db_with_gaps(["quantum computing"])
        sws = SessionWarmStarter(kg, db)
        result = sws.build_briefing("s1")
        assert " | " in result

    def test_output_is_pure_ascii(self, tmp_path):
        """Output must be ASCII-only."""
        facts = [
            {"subject": "user", "predicate": "is_a", "object": "desarrollador", "weight": 1.0},
            {"subject": "user", "predicate": "has_property", "object": "espanol", "weight": 0.9},
            {"subject": "user", "predicate": "located_in", "object": "ciudad", "weight": 0.8},
        ]
        kg = MockKG(facts=facts)
        db = _make_db_no_gaps_table()
        sws = SessionWarmStarter(kg, db)
        result = sws.build_briefing("s1")
        assert result.isascii()


class TestGapsSection:

    def test_gaps_table_missing_no_crash(self, tmp_path):
        """Missing knowledge_gaps table -> section skipped, no exception."""
        kg = MockKG(facts=_three_facts())
        db = _make_db_no_gaps_table()
        sws = SessionWarmStarter(kg, db)
        result = sws.build_briefing("s1")
        # Should still return a result (facts section only)
        assert result.startswith("Context: ")

    def test_gaps_appear_when_table_exists(self, tmp_path):
        kg = MockKG(facts=_three_facts())
        db = _make_db_with_gaps(["deep learning"])
        sws = SessionWarmStarter(kg, db)
        result = sws.build_briefing("s1")
        assert "Recent unknowns" in result
        assert "deep learning" in result


class TestMemorySection:

    def test_no_consolidator_no_crash(self, tmp_path):
        kg = MockKG(facts=_three_facts())
        db = _make_db_no_gaps_table()
        sws = SessionWarmStarter(kg, db, consolidator=None)
        result = sws.build_briefing("s1")
        assert result.startswith("Context: ")
        assert "Memory:" not in result

    def test_consolidator_summary_included(self, tmp_path):
        kg = MockKG(facts=_three_facts())
        db = _make_db_no_gaps_table()
        cons = MockConsolidator(summary="Temas recurrentes: Python, FastAPI (2 temas)")
        sws = SessionWarmStarter(kg, db, consolidator=cons)
        result = sws.build_briefing("s1")
        assert "Memory:" in result

    def test_consolidator_raises_section_skipped(self, tmp_path):
        kg = MockKG(facts=_three_facts())
        db = _make_db_no_gaps_table()
        cons = MockConsolidator(raise_on_call=True)
        sws = SessionWarmStarter(kg, db, consolidator=cons)
        result = sws.build_briefing("s1")
        # Should not crash and should not include Memory section
        assert "Memory:" not in result
        assert result.startswith("Context: ")


class TestSessionTracking:

    def test_is_first_turn_true_initially(self, tmp_path):
        kg = MockKG()
        sws = SessionWarmStarter(kg, str(tmp_path / "db.db"))
        assert sws.is_first_turn("session-abc") is True

    def test_mark_briefed_makes_is_first_turn_false(self, tmp_path):
        kg = MockKG()
        sws = SessionWarmStarter(kg, str(tmp_path / "db.db"))
        sws.mark_briefed("session-abc")
        assert sws.is_first_turn("session-abc") is False

    def test_multiple_sessions_tracked_independently(self, tmp_path):
        kg = MockKG()
        sws = SessionWarmStarter(kg, str(tmp_path / "db.db"))
        sws.mark_briefed("session-1")
        assert sws.is_first_turn("session-1") is False
        assert sws.is_first_turn("session-2") is True
        sws.mark_briefed("session-2")
        assert sws.is_first_turn("session-2") is False
        # Session 1 still False
        assert sws.is_first_turn("session-1") is False
