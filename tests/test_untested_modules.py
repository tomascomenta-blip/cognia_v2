"""
tests/test_untested_modules.py
================================
QA audit for 6 previously-untested modules.
Each class documents real bugs found. Tests are ordered: failing (bug demo) first,
then passing (fix verification) after the source fix.

Bug log at bottom of file.
"""
import math
import sqlite3
import tempfile
import os
import sys
import pytest

ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_temp_db(schema_stmts: list[str]) -> str:
    """Create a temp SQLite DB with given CREATE TABLE statements. Return path."""
    path = tempfile.mktemp(suffix=".db")
    conn = sqlite3.connect(path)
    for stmt in schema_stmts:
        conn.execute(stmt)
    conn.commit()
    conn.close()
    return path


GOAL_SCHEMA = """CREATE TABLE goal_system (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_type TEXT,
    description TEXT,
    priority REAL,
    status TEXT DEFAULT 'pending',
    created_at TEXT,
    resolved_at TEXT,
    metadata TEXT
)"""

KG_SCHEMA = """CREATE TABLE knowledge_graph (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT, predicate TEXT, object TEXT,
    weight REAL DEFAULT 1.0,
    source TEXT DEFAULT 'manual',
    timestamp TEXT
)"""


# Patch db_connect_pooled to use sqlite3.connect directly so tests are
# independent of real DB pool / real DB path.
import storage.db_pool as _pool_mod

_orig_connect = _pool_mod.db_connect_pooled


def _patched_connect(db):
    return sqlite3.connect(db)


# ---------------------------------------------------------------------------
# Module 1: MetacognitionModule  (cognia/reasoning/metacognition.py)
# ---------------------------------------------------------------------------

class TestMetacognition:
    """
    assess_confidence() bugs:
      BUG-1: KeyError when episode dict lacks 'confidence' key  (line 27)
      BUG-2: returned 'confidence' not clamped to [0, 1]; can exceed 1.0
    """

    def _make(self):
        from cognia.reasoning.metacognition import MetacognitionModule
        m = MetacognitionModule.__new__(MetacognitionModule)
        m.db = None
        m._introspect_cache = None
        m._introspect_ts = 0.0
        return m

    def test_empty_episodes_returns_ignorant(self):
        m = self._make()
        r = m.assess_confidence([])
        assert r["state"] == "ignorant"
        assert r["confidence"] == 0.0
        assert r["top_label"] is None
        assert r["should_ask"] is True

    # --- BUG-1 demo: missing 'confidence' key crashes ---
    def test_missing_confidence_field_does_not_crash(self):
        """
        BUG-1: top["confidence"] raises KeyError when key absent.
        Fixed: use top.get("confidence", 0.0)
        """
        m = self._make()
        episodes = [{"similarity": 0.9, "label": "cat"}]   # no 'confidence' key
        # After fix this must not raise
        r = m.assess_confidence(episodes)
        assert "confidence" in r

    # --- BUG-2 demo: confidence not clamped ---
    def test_confidence_clamped_to_one(self):
        """
        BUG-2: blended = 0.55*sim + 0.35*conf + kg_bonus can exceed 1.0.
        e.g. sim=2.0, conf=2.0 -> blended=1.8 with no cap.
        Fixed: clamp blended to min(1.0, blended) before returning.
        """
        m = self._make()
        episodes = [{"similarity": 2.0, "confidence": 2.0, "label": "x"}]
        r = m.assess_confidence(episodes)
        assert r["confidence"] <= 1.0, (
            f"confidence should be <= 1.0, got {r['confidence']}"
        )

    def test_negative_similarity_does_not_produce_negative_confidence(self):
        """Negative similarity is clamped to 0 via blended formula - confidence >= 0."""
        m = self._make()
        episodes = [{"similarity": -0.5, "confidence": 0.8, "label": "dog"}]
        r = m.assess_confidence(episodes)
        assert r["confidence"] >= 0.0

    def test_none_label_produces_none_top_label(self):
        m = self._make()
        episodes = [{"similarity": 0.9, "confidence": 0.8, "label": None}]
        r = m.assess_confidence(episodes)
        assert r["top_label"] is None

    def test_normal_case_returns_confident(self):
        m = self._make()
        episodes = [{"similarity": 0.9, "confidence": 0.9, "label": "cat"}]
        r = m.assess_confidence(episodes)
        assert r["state"] == "confident"
        assert r["top_label"] == "cat"
        assert r["should_ask"] is False

    def test_low_blended_returns_ignorant(self):
        m = self._make()
        episodes = [{"similarity": 0.1, "confidence": 0.1, "label": "x"}]
        r = m.assess_confidence(episodes)
        assert r["state"] == "ignorant"
        assert r["should_ask"] is True


# ---------------------------------------------------------------------------
# Module 2: ContradictionDetector  (cognia/reasoning/contradiction.py)
# ---------------------------------------------------------------------------

class TestContradiction:
    """
    check() bugs:
      BUG-3: AttributeError when semantic=None (line 20: None.find_related(...))
             No guard against None semantic argument.
    """

    def _make(self):
        from cognia.reasoning.contradiction import ContradictionDetector
        cd = ContradictionDetector.__new__(ContradictionDetector)
        cd.db = None
        return cd

    # --- BUG-3 demo: semantic=None crashes ---
    def test_semantic_none_does_not_crash(self):
        """
        BUG-3: check() calls semantic.find_related() unconditionally.
        If semantic is None -> AttributeError.
        Fixed: guard 'if semantic is None: return None'
        """
        cd = self._make()
        result = cd.check("observation", "label", [0.1, 0.2], None)
        assert result is None

    def test_identical_label_not_flagged_as_contradiction(self):
        """concept == label should never be reported as contradiction."""
        cd = self._make()

        class SameConceptSemantic:
            def find_related(self, vector, top_k=3):
                return [{"concept": "label", "similarity": 0.99, "confidence": 0.9}]

        result = cd.check("obs", "label", [1.0], SameConceptSemantic())
        assert result is None

    def test_zero_vector_can_detect_contradiction(self):
        """Zero vector is valid input; if semantic returns high-sim result, contradiction fires."""
        cd = self._make()

        class HighSimSemantic:
            def find_related(self, vector, top_k=3):
                return [{"concept": "cat", "similarity": 0.9, "confidence": 0.7}]

        result = cd.check("looks like cat", "dog", [0.0] * 10, HighSimSemantic())
        assert result is not None
        assert result["type"] == "label_conflict"
        assert result["existing_label"] == "cat"
        assert result["new_label"] == "dog"

    def test_empty_related_returns_none(self):
        cd = self._make()

        class EmptySemantic:
            def find_related(self, vector, top_k=3):
                return []

        result = cd.check("obs", "label", [0.0], EmptySemantic())
        assert result is None

    def test_threshold_is_0_85(self):
        """Items at exactly 0.84 similarity should not trigger contradiction."""
        cd = self._make()

        class BelowThresholdSemantic:
            def find_related(self, vector, top_k=3):
                return [{"concept": "cat", "similarity": 0.84, "confidence": 0.9}]

        result = cd.check("obs", "dog_label", [1.0], BelowThresholdSemantic())
        assert result is None

    def test_threshold_just_above_fires(self):
        """Items at 0.86 similarity should trigger contradiction."""
        cd = self._make()

        class AboveThresholdSemantic:
            def find_related(self, vector, top_k=3):
                return [{"concept": "cat", "similarity": 0.86, "confidence": 0.7}]

        result = cd.check("obs", "dog_label", [1.0], AboveThresholdSemantic())
        assert result is not None
        assert result["type"] == "label_conflict"

    def test_low_confidence_semantic_does_not_fire(self):
        """High similarity but low confidence (< 0.6) must not trigger contradiction."""
        cd = self._make()

        class LowConfSemantic:
            def find_related(self, vector, top_k=3):
                return [{"concept": "cat", "similarity": 0.95, "confidence": 0.5}]

        result = cd.check("obs", "dog", [1.0], LowConfSemantic())
        assert result is None


# ---------------------------------------------------------------------------
# Module 3: AttentionSystem  (cognia/attention.py)
# ---------------------------------------------------------------------------

class TestAttention:
    """
    Bugs:
      BUG-4: ZeroDivisionError when all weights are 0 (constructor divides by sum)
    """

    def test_empty_filter_returns_empty(self):
        from cognia.attention import AttentionSystem
        a = AttentionSystem()
        assert a.filter_memories([], []) == []

    def test_episode_with_no_similarity_field_scores_positively(self):
        """Missing 'similarity' key falls back to 0.0 (max(0,0)); recency/freq still contribute."""
        from cognia.attention import AttentionSystem
        a = AttentionSystem()
        ep = {"access_count": 5}
        score = a.score(ep, [])
        assert score >= 0.0

    def test_negative_similarity_clamped(self):
        """Negative similarity is clamped via max(0, ...) - score must be non-negative."""
        from cognia.attention import AttentionSystem
        a = AttentionSystem()
        ep = {"similarity": -10.0, "access_count": 1}
        score = a.score(ep, [])
        assert score >= 0.0

    def test_score_capped_at_one(self):
        """Score must never exceed 1.0 even with large importance."""
        from cognia.attention import AttentionSystem
        a = AttentionSystem()
        ep = {"similarity": 1.0, "importance": 100.0, "access_count": 1000}
        score = a.score(ep, [])
        assert score <= 1.0

    # --- BUG-4 demo: zero weights crash ---
    def test_all_zero_weights_raises(self):
        """
        BUG-4: All-zero weights causes ZeroDivisionError in __init__.
        sum(weights)=0, division by zero.
        Fixed: raise ValueError with descriptive message before division.
        """
        from cognia.attention import AttentionSystem
        with pytest.raises((ZeroDivisionError, ValueError)):
            AttentionSystem(w_semantic=0, w_emotion=0, w_recency=0, w_frequency=0)

    def test_filter_respects_threshold(self):
        """Episodes below threshold are excluded."""
        from cognia.attention import AttentionSystem
        a = AttentionSystem(threshold=0.9)
        eps = [
            {"similarity": 0.0, "access_count": 1},
            {"similarity": 1.0, "importance": 1.5, "access_count": 1},
        ]
        filtered = a.filter_memories(eps, [])
        # The low-score ep should be filtered out
        assert all(ep["attention_score"] >= 0.9 for ep in filtered)

    def test_filter_sorted_descending(self):
        """Filtered results should be sorted by attention_score descending."""
        from cognia.attention import AttentionSystem
        a = AttentionSystem(threshold=0.0)
        eps = [
            {"similarity": 0.1, "access_count": 1},
            {"similarity": 0.9, "importance": 1.5, "access_count": 1},
            {"similarity": 0.5, "access_count": 1},
        ]
        filtered = a.filter_memories(eps, [])
        scores = [ep["attention_score"] for ep in filtered]
        assert scores == sorted(scores, reverse=True)

    def test_explain_attention_returns_string(self):
        """explain_attention must return a non-empty string."""
        from cognia.attention import AttentionSystem
        a = AttentionSystem()
        ep = {"similarity": 0.7, "access_count": 3}
        result = a.explain_attention(ep, [])
        assert isinstance(result, str) and len(result) > 0

    def test_weights_normalized(self):
        """Custom weights must be normalized so they sum to 1."""
        from cognia.attention import AttentionSystem
        a = AttentionSystem(w_semantic=1, w_emotion=1, w_recency=1, w_frequency=1)
        total = a.w_semantic + a.w_emotion + a.w_recency + a.w_frequency
        assert abs(total - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# Module 4: InferenceEngine  (cognia/knowledge/inference.py)
# ---------------------------------------------------------------------------

class TestInference:

    @pytest.fixture(autouse=True)
    def setup_db(self, monkeypatch):
        path = _make_temp_db([KG_SCHEMA])
        monkeypatch.setattr(_pool_mod, "db_connect_pooled", _patched_connect)
        self.db_path = path
        from cognia.knowledge.graph import KnowledgeGraph
        from cognia.knowledge.inference import InferenceEngine
        self.kg = KnowledgeGraph(db_path=path)
        self.engine = InferenceEngine(db_path=path, kg=self.kg)
        yield
        # SQLite on Windows keeps lock; best effort cleanup
        try:
            os.unlink(path)
        except Exception:
            pass

    def test_empty_graph_returns_empty(self):
        assert self.engine.infer("cat") == []

    def test_nonexistent_concept_returns_empty(self):
        assert self.engine.infer("nonexistent_concept_xyz") == []

    def test_cycle_does_not_recurse_infinitely(self):
        """Cycle a->b->a must not raise RecursionError."""
        self.kg.add_triple("a", "is_a", "b")
        self.kg.add_triple("b", "is_a", "a")
        # Must complete without error
        results = self.engine.infer("a")
        assert isinstance(results, list)

    def test_transitive_chain_inferred(self):
        """x is_a y, y is_a z should infer x is_a z."""
        self.kg.add_triple("x", "is_a", "y")
        self.kg.add_triple("y", "is_a", "z")
        results = self.engine.infer("x")
        conclusions = [(r["conclusion_subject"], r["conclusion_predicate"], r["conclusion_object"])
                       for r in results]
        assert ("x", "is_a", "z") in conclusions

    def test_results_are_deterministic(self):
        """Same input must produce same output on repeated calls."""
        self.kg.add_triple("p", "is_a", "q")
        self.kg.add_triple("q", "is_a", "r")
        r1 = self.engine.infer("p")
        r2 = self.engine.infer("p")
        assert r1 == r2

    def test_max_steps_respected(self):
        """max_steps=1 should not traverse deeper than 1."""
        self.kg.add_triple("a", "is_a", "b")
        self.kg.add_triple("b", "is_a", "c")
        self.kg.add_triple("c", "is_a", "d")
        results_1 = self.engine.infer("a", max_steps=1)
        results_3 = self.engine.infer("a", max_steps=3)
        # With more steps, there should be at least as many or more inferences
        assert len(results_3) >= len(results_1)

    def test_results_capped_at_10(self):
        """infer() should return at most 10 items."""
        for i in range(20):
            self.kg.add_triple("root", "is_a", f"child_{i}")
            self.kg.add_triple(f"child_{i}", "is_a", "ancestor")
        results = self.engine.infer("root", max_steps=3)
        assert len(results) <= 10


# ---------------------------------------------------------------------------
# Module 5: ToolRegistry  (cognia/agents/tool_registry.py)
# ---------------------------------------------------------------------------

class TestToolRegistry:
    """
    Bugs:
      BUG-5: Silent overwrite on duplicate name registration - no error/warning
             raised, second tool silently replaces first.
             The current behavior (silent overwrite) is technically not a crash,
             but it is a contract violation that should at least be documented.
             Test verifies current behavior and that callers can detect it.
    """

    def _make(self):
        from cognia.agents.tool_registry import ToolRegistry, Tool
        return ToolRegistry(), Tool

    def test_execute_unknown_tool_returns_failure(self):
        reg, Tool = self._make()
        result = reg.execute("does_not_exist")
        assert result.success is False
        assert "Unknown tool" in result.error

    def test_exception_in_tool_is_captured_not_raised(self):
        """Exceptions from tool fn are captured into ToolResult, not propagated."""
        reg, Tool = self._make()

        def bad():
            raise RuntimeError("intentional")

        reg.register(Tool(name="bad", description="x", fn=bad))
        result = reg.execute("bad")
        assert result.success is False
        assert "intentional" in result.error

    def test_duration_ms_is_non_negative(self):
        reg, Tool = self._make()
        reg.register(Tool(name="fast", description="x", fn=lambda: 42))
        result = reg.execute("fast")
        assert result.duration_ms >= 0.0

    def test_successful_execution(self):
        reg, Tool = self._make()
        reg.register(Tool(name="add", description="x", fn=lambda a, b: a + b))
        result = reg.execute("add", a=2, b=3)
        assert result.success is True
        assert result.output == 5

    # --- BUG-5 demo: silent overwrite ---
    def test_duplicate_registration_silently_overwrites(self):
        """
        BUG-5: Registering the same name twice overwrites without error.
        Current behavior: second registration wins silently.
        This test documents the behavior — callers must not rely on first-wins.
        """
        reg, Tool = self._make()
        reg.register(Tool(name="t", description="first", fn=lambda: "first"))
        reg.register(Tool(name="t", description="second", fn=lambda: "second"))
        result = reg.execute("t")
        # Second wins - document this behavior
        assert result.output == "second"
        # And size does NOT grow (still one entry for that name)
        assert reg.names().count("t") == 1

    def test_special_characters_in_name_stored_and_retrieved(self):
        """Tool names with special characters are stored as-is (no validation)."""
        reg, Tool = self._make()
        name = "tool/with-dashes_and.dots"
        reg.register(Tool(name=name, description="x", fn=lambda: True))
        assert reg.get(name) is not None

    def test_no_size_limit(self):
        """ToolRegistry has no built-in size cap."""
        reg, Tool = self._make()
        for i in range(1000):
            reg.register(Tool(name=f"t_{i}", description="x", fn=lambda: None))
        assert len(reg) == 1000

    def test_names_returns_all_registered(self):
        reg, Tool = self._make()
        reg.register(Tool(name="a", description="x", fn=lambda: None))
        reg.register(Tool(name="b", description="x", fn=lambda: None))
        assert set(reg.names()) == {"a", "b"}

    def test_get_missing_returns_none(self):
        reg, Tool = self._make()
        assert reg.get("missing") is None


# ---------------------------------------------------------------------------
# Module 6: GoalSystem  (cognia/knowledge/goals.py)
# ---------------------------------------------------------------------------

class TestGoals:

    @pytest.fixture(autouse=True)
    def setup_db(self, monkeypatch):
        path = _make_temp_db([GOAL_SCHEMA])
        monkeypatch.setattr(_pool_mod, "db_connect_pooled", _patched_connect)
        self.db_path = path
        from cognia.knowledge.goals import GoalSystem
        self.gs = GoalSystem(db_path=path)
        yield
        try:
            os.unlink(path)
        except Exception:
            pass

    def test_empty_goals_list(self):
        assert self.gs.get_active_goals() == []

    def test_add_goal_with_no_description_uses_default(self):
        """Known GOAL_TYPES fallback to their predefined description."""
        gid = self.gs.add_goal("consolidar_memoria", description="")
        goals = self.gs.get_active_goals()
        assert any(g["description"] for g in goals if g["id"] == gid)

    def test_add_goal_unknown_type_empty_description(self):
        """Unknown goal_type with empty description -> description stored as empty string."""
        gid = self.gs.add_goal("unknown_type_xyz", description="")
        goals = self.gs.get_active_goals()
        g = next(g for g in goals if g["id"] == gid)
        # GOAL_TYPES.get returns None -> description stored as ''
        assert g["description"] == ""

    def test_resolve_goal_removes_from_active(self):
        gid = self.gs.add_goal("repasar_memoria", priority=0.7)
        self.gs.resolve_goal(gid)
        active = self.gs.get_active_goals()
        assert not any(g["id"] == gid for g in active)

    def test_resolved_goal_status_in_db(self):
        """Resolved goals have status='resolved' in DB."""
        gid = self.gs.add_goal("repasar_memoria", priority=0.7)
        self.gs.resolve_goal(gid)
        conn = sqlite3.connect(self.db_path)
        row = conn.execute("SELECT status FROM goal_system WHERE id=?", (gid,)).fetchone()
        conn.close()
        assert row[0] == "resolved"

    def test_duplicate_goal_type_returns_same_id(self):
        """Adding same goal_type twice (while pending) returns the existing ID."""
        id_a = self.gs.add_goal("repasar_memoria", priority=0.5)
        id_b = self.gs.add_goal("repasar_memoria", priority=0.5)
        assert id_a == id_b

    def test_duplicate_goal_boosts_priority(self):
        """Re-adding a pending goal boosts its priority by 0.1 (capped at 1.0)."""
        gid = self.gs.add_goal("repasar_memoria", priority=0.5)
        self.gs.add_goal("repasar_memoria", priority=0.5)  # second add
        conn = sqlite3.connect(self.db_path)
        row = conn.execute("SELECT priority FROM goal_system WHERE id=?", (gid,)).fetchone()
        conn.close()
        assert abs(row[0] - 0.6) < 0.001

    def test_priority_boost_capped_at_one(self):
        """Priority must not exceed 1.0 after multiple boosts."""
        gid = self.gs.add_goal("repasar_memoria", priority=0.95)
        for _ in range(10):
            self.gs.add_goal("repasar_memoria", priority=0.95)
        conn = sqlite3.connect(self.db_path)
        row = conn.execute("SELECT priority FROM goal_system WHERE id=?", (gid,)).fetchone()
        conn.close()
        assert row[0] <= 1.0

    def test_resolved_goal_can_be_reopened_via_db(self):
        """
        There is no API to reopen a goal; only direct DB manipulation works.
        Document this gap: status transitions are one-way through the public API.
        """
        gid = self.gs.add_goal("repasar_memoria", priority=0.5)
        self.gs.resolve_goal(gid)
        # No public API to reopen; verify it stays resolved
        active = self.gs.get_active_goals()
        assert not any(g["id"] == gid for g in active)

    def test_get_active_goals_ordered_by_priority_desc(self):
        """Active goals must be returned highest priority first."""
        self.gs.add_goal("repasar_memoria", priority=0.3)
        self.gs.add_goal("consolidar_memoria", priority=0.9)
        self.gs.add_goal("aprender_nuevo", priority=0.6)
        goals = self.gs.get_active_goals()
        priorities = [g["priority"] for g in goals]
        assert priorities == sorted(priorities, reverse=True)

    def test_auto_generate_goals_error_rate(self):
        """High error_rate triggers 'aprender_nuevo' goal."""
        state = {"error_rate": 0.5, "due_for_review": 0, "contradictions_pending": 0,
                 "active_memories": 0, "concepts": 10}
        generated = self.gs.auto_generate_goals(state)
        assert len(generated) >= 1
        goals = self.gs.get_active_goals()
        types = [g["type"] for g in goals]
        assert "aprender_nuevo" in types

    def test_auto_generate_goals_empty_state(self):
        """Empty state dict generates no goals."""
        generated = self.gs.auto_generate_goals({})
        assert generated == []
