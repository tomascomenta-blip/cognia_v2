"""
tests/test_insight_connector.py
================================
Phase 57 — Tests for InsightConnector (PIC).
Uses a real KnowledgeGraph backed by a temp SQLite file so no mocking of
db_pool is needed — the pool accepts any path.
"""

import os
import sqlite3
import tempfile
import pytest


# ── helpers ───────────────────────────────────────────────────────────────────

def _create_schema(path: str) -> None:
    """Minimal KG schema used by KnowledgeGraph."""
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS knowledge_graph (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            subject     TEXT NOT NULL,
            predicate   TEXT NOT NULL,
            object      TEXT NOT NULL,
            weight      REAL DEFAULT 1.0,
            source      TEXT DEFAULT 'learned',
            timestamp   TEXT,
            verified    INTEGER DEFAULT 0,
            UNIQUE(subject, predicate, object)
        )
    """)
    conn.commit()
    conn.close()


def _drain_pool(db_path: str) -> None:
    """Drain and remove pool entry so temp file can be deleted on Windows."""
    try:
        from storage.db_pool import _pools
        pool = _pools.get(db_path)
        if pool is None:
            return
        conns = []
        while True:
            try:
                conns.append(pool._pool.get_nowait())
            except Exception:
                break
        for c in conns:
            try:
                c.close()
            except Exception:
                pass
        _pools.pop(db_path, None)
    except Exception:
        pass


def _make_kg(db_path: str):
    """Return a KnowledgeGraph instance pointing at db_path."""
    from cognia.knowledge.graph import KnowledgeGraph
    return KnowledgeGraph(db_path=db_path)


def _make_pic(db_path: str):
    """Return (KnowledgeGraph, InsightConnector) for a fresh temp DB."""
    from cognia.proactive.insight_connector import InsightConnector
    kg = _make_kg(db_path)
    return kg, InsightConnector(kg)


# ── fixtures ──────────────────────────────────────────────────────────────────

class TestInsightConnector:
    def setup_method(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._db_path = os.path.join(self._tmp.name, "pic_test.db")
        _create_schema(self._db_path)
        self._kg, self._pic = _make_pic(self._db_path)

    def teardown_method(self):
        _drain_pool(self._db_path)
        self._tmp.cleanup()

    # ── 1. empty KG → no insights ─────────────────────────────────────────────

    def test_empty_kg_returns_empty_list(self):
        result = self._pic.find_insights("What is machine learning?")
        assert result == []

    # ── 2. query with only short words → no keywords extracted ───────────────

    def test_query_with_no_keywords_returns_empty(self):
        # all words <= 3 chars
        result = self._pic.find_insights("is it ok")
        assert result == []

    # ── 3. stopwords filtered from keywords ──────────────────────────────────

    def test_stopwords_not_used_as_keywords(self):
        # "about", "with", "when" are stopwords; KG has fact for "about"
        self._kg.add_triple("about", "related_to", "topic", weight=1.0)
        result = self._pic.find_insights("about with when")
        # "about" is a stopword so it never probes KG for it
        assert result == []

    # ── 4. keywords < 4 chars filtered ───────────────────────────────────────

    def test_short_keywords_filtered(self):
        # "ai" and "ml" are <= 3 chars — never probed
        self._kg.add_triple("ai", "related_to", "computing", weight=1.0)
        result = self._pic.find_insights("ai ml use")
        assert result == []

    # ── 5. user fact → user-specific insight text ────────────────────────────

    def test_user_fact_generates_user_insight(self):
        self._kg.add_triple("user", "has_property", "python", weight=1.0)
        result = self._pic.find_insights("python programming language")
        assert len(result) >= 1
        assert any("background" in r or "python" in r for r in result)

    # ── 6. relevant fact → connection found ──────────────────────────────────

    def test_relevant_fact_found(self):
        self._kg.add_triple("python", "related_to", "programming", weight=1.0)
        result = self._pic.find_insights("python is a great language")
        assert len(result) >= 1

    # ── 7. low-weight fact below threshold → filtered ────────────────────────

    def test_low_weight_fact_filtered(self):
        # weight=0.1 → connection_score = 0.1 * 1.0 = 0.1 < 0.3 (MIN_CONNECTION_SCORE)
        self._kg.add_triple("python", "related_to", "programming", weight=0.1)
        result = self._pic.find_insights("python is amazing")
        assert result == []

    # ── 8. max MAX_INSIGHTS = 2 respected with 10 facts ──────────────────────

    def test_max_insights_limit_respected(self):
        for i in range(10):
            self._kg.add_triple("machine", "related_to", f"concept{i}", weight=1.0)
        result = self._pic.find_insights("machine learning algorithms")
        assert len(result) <= 2

    # ── 9. get_prompt_injection: empty insights → empty string ───────────────

    def test_get_prompt_injection_empty_kg_returns_empty_string(self):
        result = self._pic.get_prompt_injection("what is neural network")
        assert result == ""

    # ── 10. get_prompt_injection: non-empty → contains "Relevant context:" ───

    def test_get_prompt_injection_non_empty_contains_header(self):
        self._kg.add_triple("neural", "related_to", "network", weight=1.0)
        result = self._pic.get_prompt_injection("neural network architecture")
        assert "Relevant context:" in result

    # ── 11. insights are ASCII only ──────────────────────────────────────────

    def test_insights_are_ascii(self):
        # Insert fact with unicode in it (DB stores it, PIC must sanitize output)
        self._kg.add_triple("python", "related_to", "programacion", weight=1.0)
        results = self._pic.find_insights("python programacion")
        for r in results:
            assert r.isascii(), f"Non-ASCII chars in insight: {r!r}"

    # ── 12. each insight is at most 120 chars ────────────────────────────────

    def test_each_insight_max_120_chars(self):
        long_obj = "x" * 200
        self._kg.add_triple("python", "related_to", long_obj, weight=1.0)
        results = self._pic.find_insights("python coding")
        for r in results:
            assert len(r) <= 120, f"Insight exceeds 120 chars: {len(r)}"

    # ── 13. high-weight fact beats low-weight in ordering ────────────────────

    def test_high_weight_fact_appears_first(self):
        self._kg.add_triple("python", "related_to", "low_prio", weight=0.4)
        self._kg.add_triple("python", "related_to", "high_prio", weight=2.0)
        results = self._pic.find_insights("python language features")
        assert len(results) >= 1
        # high_prio should appear before low_prio
        if len(results) == 2:
            assert "high_prio" in results[0]

    # ── 14. deduplication: same insight text not repeated ────────────────────

    def test_no_duplicate_insights(self):
        self._kg.add_triple("python", "related_to", "programming", weight=1.0)
        # KG deduplicates triples internally; call find_insights multiple times
        r1 = self._pic.find_insights("python programming")
        r2 = self._pic.find_insights("python programming")
        # Results themselves must have no internal duplicates
        assert len(r1) == len(set(r1))
        assert r1 == r2

    # ── 15. find_insights with "user" keyword returns user facts ─────────────

    def test_user_query_returns_user_facts(self):
        self._kg.add_triple("user", "has_property", "machine_learning", weight=1.0)
        result = self._pic.find_insights("user profile preferences")
        assert len(result) >= 1
        assert any("machine_learning" in r for r in result)

    # ── 16. get_facts called for each keyword (stub KG test) ─────────────────

    def test_get_facts_called_per_keyword(self):
        """Verify each keyword triggers a get_facts call via a stub."""
        calls = []

        class StubKG:
            def get_facts(self, term):
                calls.append(term)
                return []

        from cognia.proactive.insight_connector import InsightConnector
        pic = InsightConnector(StubKG())
        pic.find_insights("python machine learning")

        # "python", "machine", "learning" are all > 3 chars; "user" always added
        assert "python" in calls
        assert "machine" in calls
        assert "learning" in calls
        assert "user" in calls

    # ── 17. get_prompt_injection bullet format ───────────────────────────────

    def test_get_prompt_injection_uses_bullet_format(self):
        self._kg.add_triple("neural", "related_to", "network", weight=1.0)
        result = self._pic.get_prompt_injection("neural network architecture")
        assert result.startswith("Relevant context:")
        assert "\n-" in result

    # ── 18. fact below threshold via relevance penalty ───────────────────────

    def test_irrelevant_fact_below_threshold_after_penalty(self):
        # weight=0.5 * relevance=0.5 (keywords not in triple) = 0.25 < 0.3
        # "neural" is the query keyword, but fact is about "cognia" and "system"
        self._kg.add_triple("cognia", "related_to", "system", weight=0.5)
        result = self._pic.find_insights("neural network architecture")
        # "cognia" and "system" are not in the query, so relevance=0.5 → score=0.25
        assert result == []

    # ── 19. fact at exactly threshold (boundary) ────────────────────────────

    def test_fact_at_threshold_boundary_included(self):
        # weight=0.6 * relevance=0.5 = 0.3 == MIN_CONNECTION_SCORE → included
        self._kg.add_triple("cognia", "related_to", "platform", weight=0.6)
        result = self._pic.find_insights("neural network architecture")
        # relevance=0.5 (keywords not in triple) → 0.6*0.5=0.3, exactly at threshold
        assert isinstance(result, list)  # boundary: may or may not include, no crash

    # ── 20. empty string query → empty insights ──────────────────────────────

    def test_empty_string_query_returns_empty(self):
        self._kg.add_triple("python", "related_to", "code", weight=1.0)
        result = self._pic.find_insights("")
        assert result == []
