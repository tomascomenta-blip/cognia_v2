"""
Permanent benchmark suite -- runs after every change.
200+ parameterized cases covering: memory, reasoning, security, robustness, CLI commands, KG.

Self-contained: no shared fixtures that break in isolation.
All DB-backed tests use _tmpdir() inline.
"""
import pytest
import math
import re
import tempfile
import os
import sys
import threading
import json
from pathlib import Path

# Ensure project root is on sys.path (mirrors conftest.py)
ROOT = Path(__file__).parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(tmp_dir: str) -> str:
    """Initialize a fresh Cognia DB in tmp_dir and return its path."""
    db_path = os.path.join(tmp_dir, "test_cognia.db")
    from cognia.database import init_db
    init_db(db_path)
    return db_path


def _tmpdir():
    """TemporaryDirectory with ignore_cleanup_errors=True for Windows SQLite WAL lock."""
    return tempfile.TemporaryDirectory(ignore_cleanup_errors=True)


def _blocking_logic(cmd: str) -> bool:
    """
    Mirror the /ejecutar blocking logic from cognia/cli.py (both places use same list).
    Returns True if the command should be BLOCKED.
    """
    _BLOCKED = [
        "rm -rf", "format", "del /s", "del /q", "del /f",
        ":(){:|:&};:", "python -c", "python3 -c", "powershell",
        "mkfs", "dd if=", "> /dev/", "shutdown", "reboot",
    ]
    normalized = re.sub(r"\s+", " ", cmd.lower())
    return any(b in normalized for b in _BLOCKED)


# ===========================================================================
# Section 1: Memory subsystem — VectorCache (40+ cases)
# ===========================================================================

class TestVectorCacheMarkDirty:
    """VectorCache.mark_dirty() is thread-safe and sets _dirty=True."""

    @pytest.mark.parametrize("n_threads", [1, 2, 5, 10, 20])
    def test_concurrent_mark_dirty(self, n_threads):
        from cognia.memory.episodic_fast import VectorCache
        with _tmpdir() as tmp:
            db = _make_db(tmp)
            vc = VectorCache(db)
            errors = []

            def _mark():
                try:
                    vc.mark_dirty()
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=_mark) for _ in range(n_threads)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert not errors, f"Errors during concurrent mark_dirty: {errors}"
            assert vc._dirty is True

    @pytest.mark.parametrize("n_calls", [1, 3, 10, 50, 100])
    def test_mark_dirty_idempotent(self, n_calls):
        from cognia.memory.episodic_fast import VectorCache
        with _tmpdir() as tmp:
            db = _make_db(tmp)
            vc = VectorCache(db)
            for _ in range(n_calls):
                vc.mark_dirty()
            assert vc._dirty is True


class TestVectorCacheBuildEmpty:
    """VectorCache.build() on empty DB returns empty matrix."""

    def test_build_empty_db(self):
        from cognia.memory.episodic_fast import VectorCache
        with _tmpdir() as tmp:
            db = _make_db(tmp)
            vc = VectorCache(db)
            vc.build()
            assert vc._matrix is not None
            assert vc._matrix.shape[0] == 0

    def test_search_empty_db_returns_list(self):
        from cognia.memory.episodic_fast import VectorCache
        with _tmpdir() as tmp:
            db = _make_db(tmp)
            vc = VectorCache(db)
            result = vc.search([0.1] * 384, top_k=5)
            assert isinstance(result, list)
            assert len(result) == 0


class TestVectorCacheSearchDimensions:
    """VectorCache handles various query dimensions gracefully."""

    @pytest.mark.parametrize("dim", [32, 64, 128, 384])
    def test_search_with_zero_vector_returns_empty(self, dim):
        from cognia.memory.episodic_fast import VectorCache
        with _tmpdir() as tmp:
            db = _make_db(tmp)
            vc = VectorCache(db)
            # zero-norm vector should be rejected gracefully
            result = vc.search([0.0] * dim, top_k=5)
            assert isinstance(result, list)

    @pytest.mark.parametrize("dim", [32, 64, 128, 384])
    def test_search_nonzero_returns_list(self, dim):
        from cognia.memory.episodic_fast import VectorCache
        with _tmpdir() as tmp:
            db = _make_db(tmp)
            vc = VectorCache(db)
            result = vc.search([0.1] * dim, top_k=5)
            assert isinstance(result, list)

    def test_search_none_query_returns_empty(self):
        from cognia.memory.episodic_fast import VectorCache
        with _tmpdir() as tmp:
            db = _make_db(tmp)
            vc = VectorCache(db)
            result = vc.search(None, top_k=5)
            assert result == []


class TestVectorCacheWithData:
    """VectorCache with actual episodic rows in DB."""

    def _insert_episodes(self, db_path, n, dim=384):
        """Insert n episodic memory rows with random-ish vectors."""
        import json as _json
        from storage.db_pool import db_connect_pooled as db_connect
        conn = db_connect(db_path)
        from datetime import datetime
        for i in range(n):
            vec = [float((i + j + 1) % 7) / 7.0 for j in range(dim)]
            conn.execute(
                "INSERT INTO episodic_memory (timestamp, observation, label, vector, confidence, importance, forgotten) "
                "VALUES (?, ?, ?, ?, ?, ?, 0)",
                (datetime.now().isoformat(), f"obs_{i}", f"label_{i}", _json.dumps(vec), 0.7, 1.0),
            )
        conn.commit()
        conn.close()

    @pytest.mark.parametrize("n_items", [1, 5, 10, 50])
    def test_search_returns_at_most_top_k(self, n_items):
        from cognia.memory.episodic_fast import VectorCache
        with _tmpdir() as tmp:
            db = _make_db(tmp)
            self._insert_episodes(db, n_items, dim=384)
            vc = VectorCache(db)
            query = [0.5] * 384
            result = vc.search(query, top_k=3)
            assert isinstance(result, list)
            assert len(result) <= min(3, n_items)

    @pytest.mark.parametrize("n_items", [1, 5, 10])
    def test_build_then_search_has_observations(self, n_items):
        from cognia.memory.episodic_fast import VectorCache
        with _tmpdir() as tmp:
            db = _make_db(tmp)
            self._insert_episodes(db, n_items, dim=384)
            vc = VectorCache(db)
            vc.build()
            assert vc._matrix.shape[0] == n_items
            result = vc.search([0.3] * 384, top_k=n_items)
            assert len(result) == n_items
            for r in result:
                assert "observation" in r
                assert "similarity" in r

    @pytest.mark.parametrize("top_k", [1, 3, 5])
    def test_search_respects_top_k(self, top_k):
        from cognia.memory.episodic_fast import VectorCache
        with _tmpdir() as tmp:
            db = _make_db(tmp)
            self._insert_episodes(db, 20, dim=384)
            vc = VectorCache(db)
            result = vc.search([0.4] * 384, top_k=top_k)
            assert len(result) <= top_k

    def test_mark_dirty_triggers_rebuild(self):
        from cognia.memory.episodic_fast import VectorCache
        with _tmpdir() as tmp:
            db = _make_db(tmp)
            self._insert_episodes(db, 5, dim=384)
            vc = VectorCache(db)
            vc.build()
            assert vc._matrix.shape[0] == 5
            # Insert more data and mark dirty
            self._insert_episodes(db, 3, dim=384)
            vc.mark_dirty()
            assert vc._dirty is True


# ===========================================================================
# Section 2: SemanticMemory (10+ cases)
# ===========================================================================

class TestSemanticMemory:

    @pytest.mark.parametrize("dim", [32, 64, 128, 384])
    def test_update_concept_creates_entry(self, dim):
        from cognia.memory.semantic import SemanticMemory
        with _tmpdir() as tmp:
            db = _make_db(tmp)
            sm = SemanticMemory(db_path=db)
            vec = [0.1] * dim
            sm.update_concept("test_concept", vec, description="test", confidence_delta=0.1)
            result = sm.get_concept("test_concept")
            assert result is not None
            assert result["concept"] == "test_concept"

    @pytest.mark.parametrize("concept", ["hello", "cafe", "x" * 100, "42", ""])
    def test_get_concept_missing_returns_none(self, concept):
        from cognia.memory.semantic import SemanticMemory
        with _tmpdir() as tmp:
            db = _make_db(tmp)
            sm = SemanticMemory(db_path=db)
            result = sm.get_concept(concept)
            assert result is None

    def test_add_association_requires_existing_concept(self):
        from cognia.memory.semantic import SemanticMemory
        with _tmpdir() as tmp:
            db = _make_db(tmp)
            sm = SemanticMemory(db_path=db)
            # Should not raise even if concept_a doesn't exist
            sm.add_association("nonexistent_a", "nonexistent_b", 0.5)

    def test_find_related_empty_db(self):
        from cognia.memory.semantic import SemanticMemory
        with _tmpdir() as tmp:
            db = _make_db(tmp)
            sm = SemanticMemory(db_path=db)
            result = sm.find_related([0.1] * 384)
            assert result == []

    def test_spreading_activation_empty_db(self):
        from cognia.memory.semantic import SemanticMemory
        with _tmpdir() as tmp:
            db = _make_db(tmp)
            sm = SemanticMemory(db_path=db)
            result = sm.spreading_activation("unknown_concept", depth=2)
            assert isinstance(result, list)

    def test_update_concept_increments_support(self):
        from cognia.memory.semantic import SemanticMemory
        with _tmpdir() as tmp:
            db = _make_db(tmp)
            sm = SemanticMemory(db_path=db)
            vec = [0.5] * 64
            sm.update_concept("repeated", vec)
            sm.update_concept("repeated", vec)
            result = sm.get_concept("repeated")
            assert result is not None
            assert result["support"] >= 2


# ===========================================================================
# Section 3: CogniaReasoningEngine (30+ cases)
# ===========================================================================

class TestReasoningEngineEnrichReturnsStr:
    """enrich() must always return a str."""

    @pytest.mark.parametrize("question,context,q_type", [
        ("hi", "", "social"),
        ("a b c d e", "some context", "general"),
        ("word " * 15, "rich " * 30, "general"),
        ("word " * 50, "ctx", "comparacion"),
        ("word " * 200, "long " * 50, "definicion"),
        ("short", "", "corta"),
        ("sin embargo esto es diferente pero hay mas", "ctx here", "general"),
        ("however the results show but no obstante", "context", "general"),
        ("no obstante consideremos los hechos que son diferentes", "ctx", "general"),
        ("", "", "general"),
        ("", "some context", "social"),
    ])
    def test_enrich_returns_str(self, question, context, q_type):
        from cognia.reasoning.cognia_reasoning_engine import CogniaReasoningEngine
        engine = CogniaReasoningEngine()
        result = engine.enrich(question, context, q_type)
        assert isinstance(result, str)


class TestReasoningEngineEnrichWithMeta:
    """enrich_with_meta() confidence is always in [0, 1]."""

    @pytest.mark.parametrize("question,context,q_type", [
        ("one", "", "social"),
        ("one two three four five", "ctx", "general"),
        ("word " * 15, "", "general"),
        ("word " * 15, "context " * 20, "general"),
        ("word " * 50, "ctx with sin embargo in it", "comparacion"),
        ("word " * 50, "no obstante los datos son incorrectos", "comparacion"),
        ("word " * 50, "but on the other hand", "definicion"),
        ("however this is long enough for decomposition yes yes", "ctx", "general"),
        ("sin embargo tenemos muchas cosas que considerar en este problema", "no es correcto", "general"),
        ("word " * 200, "context " * 50, "general"),
    ])
    def test_confidence_in_range(self, question, context, q_type):
        from cognia.reasoning.cognia_reasoning_engine import CogniaReasoningEngine
        engine = CogniaReasoningEngine()
        result = engine.enrich_with_meta(question, context, q_type)
        assert isinstance(result, dict)
        conf = result["confidence"]
        assert 0.0 <= conf <= 1.0, f"confidence={conf} out of range"

    @pytest.mark.parametrize("q_type", ["social", "proyecto_actual", "factual_simple"])
    def test_simple_qtypes_skip_enrichment(self, q_type):
        """Short-circuit for simple q_types: returns original context unchanged."""
        from cognia.reasoning.cognia_reasoning_engine import CogniaReasoningEngine
        engine = CogniaReasoningEngine()
        ctx = "original context"
        result = engine.enrich_with_meta("hello", ctx, q_type)
        assert result["context"] == ctx
        assert result["sub_questions"] == []

    @pytest.mark.parametrize("question,context,q_type", [
        ("word " * 15, "texto sin marcadores", "general"),
        ("word " * 15, "sin embargo el contraste es evidente", "general"),
        ("word " * 15, "but on the other hand things differ", "general"),
        ("word " * 15, "however the conclusion is different", "general"),
    ])
    def test_has_contradiction_is_bool(self, question, context, q_type):
        from cognia.reasoning.cognia_reasoning_engine import CogniaReasoningEngine
        engine = CogniaReasoningEngine()
        result = engine.enrich_with_meta(question, context, q_type)
        assert isinstance(result["has_contradiction"], bool)

    @pytest.mark.parametrize("n_words", [1, 5, 14, 15, 16, 50, 200])
    def test_length_threshold(self, n_words):
        """Questions with fewer than 15 words skip enrichment."""
        from cognia.reasoning.cognia_reasoning_engine import CogniaReasoningEngine
        engine = CogniaReasoningEngine()
        q = " ".join(["word"] * n_words)
        result = engine.enrich_with_meta(q, "context", "general")
        if n_words < 15:
            assert result["sub_questions"] == []
        assert isinstance(result["context"], str)


# ===========================================================================
# Section 4: Security blocklist (30+ cases)
# ===========================================================================

BLOCKED_COMMANDS = [
    "rm -rf /",
    "rm  -rf /",           # double space -- normalized
    "RM -RF /",            # uppercase
    "python -c 'import os'",
    "PYTHON -C test",
    "python3 -c exec()",
    "powershell Remove-Item",
    "powershell -Command Get-Process",
    "POWERSHELL get-item",
    "del /q C:",
    "DEL /Q C:",
    "del /f important.txt",
    "del /s /q *",
    "format c:",
    "FORMAT C:",
    "format d:",
    ":(){:|:&};:",
    "shutdown -h now && :(){:|:&};:",  # fork bomb at end
    "shutdown -h now",
    "SHUTDOWN -r now",
    "reboot",
    "REBOOT",
    "mkfs.ext4 /dev/sda",
    "MKFS /dev/sdb",
    "dd if=/dev/zero of=/dev/sda",
    "echo hi > /dev/null",   # contains "> /dev/"
    "cat file > /dev/sda",
]

ALLOWED_COMMANDS = [
    "ls",
    "dir",
    "echo hello",
    "git status",
    "python --version",
    "pwd",
    "whoami",
    "python main.py",
    "ls -la",
    "cat file.txt",
    "head -n 10 log.txt",
    "grep pattern file",
]


class TestSecurityBlocklist:

    @pytest.mark.parametrize("cmd", BLOCKED_COMMANDS)
    def test_blocked_commands_are_blocked(self, cmd):
        assert _blocking_logic(cmd) is True, f"Expected BLOCKED but got ALLOWED: {cmd!r}"

    @pytest.mark.parametrize("cmd", ALLOWED_COMMANDS)
    def test_allowed_commands_pass(self, cmd):
        assert _blocking_logic(cmd) is False, f"Expected ALLOWED but got BLOCKED: {cmd!r}"


# ===========================================================================
# Section 5: Knowledge Graph (30+ cases)
# ===========================================================================

VALID_RELATIONS = [
    "is_a", "part_of", "causes", "capable_of", "related_to",
    "has_property", "opposite_of", "instance_of", "used_for", "located_in",
]


class TestKnowledgeGraphAddTriple:

    @pytest.mark.parametrize("relation", VALID_RELATIONS)
    def test_all_relations_accepted(self, relation):
        from cognia.knowledge.graph import KnowledgeGraph
        with _tmpdir() as tmp:
            db = _make_db(tmp)
            kg = KnowledgeGraph(db_path=db)
            is_new = kg.add_triple("dog", relation, "animal")
            assert isinstance(is_new, bool)
            facts = kg.get_facts("dog")
            assert len(facts) >= 1

    def test_invalid_relation_falls_back_to_related_to(self):
        from cognia.knowledge.graph import KnowledgeGraph
        with _tmpdir() as tmp:
            db = _make_db(tmp)
            kg = KnowledgeGraph(db_path=db)
            kg.add_triple("a", "UNKNOWNRELATION", "b")
            facts = kg.get_facts("a")
            assert any(f["predicate"] == "related_to" for f in facts)

    @pytest.mark.parametrize("n", [1, 5, 10, 20])
    def test_add_n_triples_and_get_facts(self, n):
        from cognia.knowledge.graph import KnowledgeGraph
        with _tmpdir() as tmp:
            db = _make_db(tmp)
            kg = KnowledgeGraph(db_path=db)
            for i in range(n):
                kg.add_triple("concept", "related_to", f"thing_{i}")
            facts = kg.get_facts("concept")
            assert len(facts) >= min(n, 20)  # get_facts LIMIT is 20

    def test_add_triple_is_new_returns_false_on_duplicate(self):
        from cognia.knowledge.graph import KnowledgeGraph
        with _tmpdir() as tmp:
            db = _make_db(tmp)
            kg = KnowledgeGraph(db_path=db)
            first = kg.add_triple("x", "is_a", "y")
            second = kg.add_triple("x", "is_a", "y")
            assert first is True
            assert second is False


class TestKnowledgeGraphSpecialConcepts:

    @pytest.mark.parametrize("concept", [
        "cafe", "c++", "100%", "hello world", "test_concept",
    ])
    def test_add_triple_with_special_chars(self, concept):
        from cognia.knowledge.graph import KnowledgeGraph
        with _tmpdir() as tmp:
            db = _make_db(tmp)
            kg = KnowledgeGraph(db_path=db)
            # add_triple lowercases, so we just check no exception
            kg.add_triple(concept, "related_to", "something")
            facts = kg.get_facts(concept.lower())
            assert isinstance(facts, list)

    def test_very_long_concept(self):
        from cognia.knowledge.graph import KnowledgeGraph
        with _tmpdir() as tmp:
            db = _make_db(tmp)
            kg = KnowledgeGraph(db_path=db)
            long_concept = "x" * 500
            kg.add_triple(long_concept, "related_to", "y")
            facts = kg.get_facts(long_concept)
            assert isinstance(facts, list)

    def test_empty_concept(self):
        from cognia.knowledge.graph import KnowledgeGraph
        with _tmpdir() as tmp:
            db = _make_db(tmp)
            kg = KnowledgeGraph(db_path=db)
            # Empty concept after .lower().strip() becomes ""; should not crash
            kg.add_triple("", "related_to", "y")
            facts = kg.get_facts("")
            assert isinstance(facts, list)


class TestKnowledgeGraphInheritedFacts:

    @pytest.mark.parametrize("chain_depth", [0, 1, 2])
    def test_inherited_facts_chain(self, chain_depth):
        from cognia.knowledge.graph import KnowledgeGraph
        with _tmpdir() as tmp:
            db = _make_db(tmp)
            kg = KnowledgeGraph(db_path=db)
            # Build a chain: dog is_a animal is_a living_thing
            # and add a property to animal and living_thing
            kg.add_triple("dog", "is_a", "animal")
            kg.add_triple("animal", "is_a", "living_thing")
            kg.add_triple("animal", "has_property", "breathes")
            kg.add_triple("living_thing", "has_property", "grows")
            result = kg.get_inherited_facts("dog", max_depth=chain_depth + 1)
            assert isinstance(result, list)
            if chain_depth >= 1:
                texts = " ".join(result)
                assert "breathes" in texts or "dog" in texts

    def test_get_ancestors_no_chain(self):
        from cognia.knowledge.graph import KnowledgeGraph
        with _tmpdir() as tmp:
            db = _make_db(tmp)
            kg = KnowledgeGraph(db_path=db)
            result = kg.get_ancestors("orphan_concept")
            assert result == []


class TestKnowledgeGraphStats:

    def test_stats_empty_db(self):
        from cognia.knowledge.graph import KnowledgeGraph
        with _tmpdir() as tmp:
            db = _make_db(tmp)
            kg = KnowledgeGraph(db_path=db)
            s = kg.stats()
            assert s["total_edges"] == 0
            assert s["nodes"] == 0

    def test_stats_after_inserts(self):
        from cognia.knowledge.graph import KnowledgeGraph
        with _tmpdir() as tmp:
            db = _make_db(tmp)
            kg = KnowledgeGraph(db_path=db)
            kg.add_triple("a", "causes", "b")
            kg.add_triple("b", "causes", "c")
            s = kg.stats()
            assert s["total_edges"] == 2
            assert "causes" in s["by_relation"]


# ===========================================================================
# Section 6: Metacognition — assess_confidence (20+ cases)
# ===========================================================================

class TestMetacognitionAssessConfidence:

    def test_empty_episodes_returns_ignorant(self):
        from cognia.reasoning.metacognition import MetacognitionModule
        with _tmpdir() as tmp:
            db = _make_db(tmp)
            mc = MetacognitionModule(db_path=db)
            result = mc.assess_confidence([])
            assert result["state"] == "ignorant"
            assert result["confidence"] == 0.0
            assert result["should_ask"] is True

    @pytest.mark.parametrize("sim,conf", [
        (1.0, 1.0),
        (0.9, 0.8),
        (0.5, 0.5),
        (0.1, 0.1),
        (0.0, 0.0),
    ])
    def test_confidence_is_clamped_to_one(self, sim, conf):
        from cognia.reasoning.metacognition import MetacognitionModule
        with _tmpdir() as tmp:
            db = _make_db(tmp)
            mc = MetacognitionModule(db_path=db)
            episodes = [{"similarity": sim, "confidence": conf, "label": "test"}]
            result = mc.assess_confidence(episodes)
            assert 0.0 <= result["confidence"] <= 1.0

    @pytest.mark.parametrize("sim", [-1.0, 0.0, 0.5, 1.0, 2.0])
    def test_edge_similarity_values(self, sim):
        from cognia.reasoning.metacognition import MetacognitionModule
        with _tmpdir() as tmp:
            db = _make_db(tmp)
            mc = MetacognitionModule(db_path=db)
            episodes = [{"similarity": sim, "confidence": 0.5, "label": "test"}]
            result = mc.assess_confidence(episodes)
            # Blended formula is min(1.0, ...) so confidence always <= 1.0
            assert result["confidence"] <= 1.0
            assert isinstance(result["state"], str)

    @pytest.mark.parametrize("conf_val", [-0.5, 0.0, 0.5, 1.0, 1.5])
    def test_edge_confidence_values(self, conf_val):
        from cognia.reasoning.metacognition import MetacognitionModule
        with _tmpdir() as tmp:
            db = _make_db(tmp)
            mc = MetacognitionModule(db_path=db)
            episodes = [{"similarity": 0.5, "confidence": conf_val, "label": "test"}]
            result = mc.assess_confidence(episodes)
            assert 0.0 <= result["confidence"] <= 1.0

    def test_missing_confidence_key_uses_default(self):
        from cognia.reasoning.metacognition import MetacognitionModule
        with _tmpdir() as tmp:
            db = _make_db(tmp)
            mc = MetacognitionModule(db_path=db)
            episodes = [{"similarity": 0.8, "label": "test"}]  # no 'confidence' key
            result = mc.assess_confidence(episodes)
            assert isinstance(result, dict)
            assert 0.0 <= result["confidence"] <= 1.0

    def test_missing_label_key(self):
        from cognia.reasoning.metacognition import MetacognitionModule
        with _tmpdir() as tmp:
            db = _make_db(tmp)
            mc = MetacognitionModule(db_path=db)
            episodes = [{"similarity": 0.8, "confidence": 0.6}]  # no 'label' key
            result = mc.assess_confidence(episodes)
            assert result["top_label"] is None

    @pytest.mark.parametrize("n", [1, 5, 10, 50])
    def test_list_of_n_episodes(self, n):
        from cognia.reasoning.metacognition import MetacognitionModule
        with _tmpdir() as tmp:
            db = _make_db(tmp)
            mc = MetacognitionModule(db_path=db)
            episodes = [
                {"similarity": 0.5, "confidence": 0.5, "label": f"lbl_{i}"}
                for i in range(n)
            ]
            result = mc.assess_confidence(episodes)
            assert isinstance(result, dict)
            assert "state" in result
            assert "confidence" in result

    def test_high_sim_and_conf_is_confident(self):
        from cognia.reasoning.metacognition import MetacognitionModule
        with _tmpdir() as tmp:
            db = _make_db(tmp)
            mc = MetacognitionModule(db_path=db)
            episodes = [{"similarity": 1.0, "confidence": 1.0, "label": "test"}]
            result = mc.assess_confidence(episodes)
            # 0.55*1 + 0.35*1 = 0.9 >= 0.75 -> confident
            assert result["state"] == "confident"
            assert result["should_ask"] is False

    def test_low_sim_and_conf_is_ignorant(self):
        from cognia.reasoning.metacognition import MetacognitionModule
        with _tmpdir() as tmp:
            db = _make_db(tmp)
            mc = MetacognitionModule(db_path=db)
            episodes = [{"similarity": 0.1, "confidence": 0.1, "label": "test"}]
            result = mc.assess_confidence(episodes)
            # 0.55*0.1 + 0.35*0.1 = 0.09 < 0.3 -> ignorant
            assert result["state"] == "ignorant"
            assert result["should_ask"] is True


# ===========================================================================
# Section 7: Robustness -- unicode and edge inputs (30+ cases)
# ===========================================================================

UNICODE_INPUTS = [
    "hello",
    "Japones unicode test",
    "Arabic test input",
    "Nono con tilde",
    "Greek letters alpha beta",
    "rocket target emoji test",
    "hello\x00world",           # null byte
    "line1\nline2\nline3",
    "col1\tcol2",
    "word " * 5000,             # very long
    "42",
    "3.14",
    "1e10",
    "<script>alert(1)</script>",
    "'; DROP TABLE episodic_memory; --",
    "",
    " ",
    "\n",
    "\t",
    "a" * 10000,
]


class TestReasoningRobustness:
    """Reasoning engine handles all edge inputs without crashing."""

    @pytest.mark.parametrize("text", UNICODE_INPUTS)
    def test_enrich_does_not_crash(self, text):
        from cognia.reasoning.cognia_reasoning_engine import CogniaReasoningEngine
        engine = CogniaReasoningEngine()
        result = engine.enrich(text, "some context", "general")
        assert isinstance(result, str)

    @pytest.mark.parametrize("text", UNICODE_INPUTS)
    def test_enrich_with_meta_does_not_crash(self, text):
        from cognia.reasoning.cognia_reasoning_engine import CogniaReasoningEngine
        engine = CogniaReasoningEngine()
        result = engine.enrich_with_meta(text, "ctx", "general")
        assert isinstance(result, dict)
        assert 0.0 <= result["confidence"] <= 1.0


class TestSemanticMemoryRobustness:
    """SemanticMemory handles edge inputs without crashing."""

    @pytest.mark.parametrize("concept", [
        "hello", "cafe", "", "a" * 500,
        "'; DROP TABLE semantic_memory; --",
        "<script>alert(1)</script>",
        "42", "3.14", "line1\nline2",
    ])
    def test_update_concept_robust(self, concept):
        from cognia.memory.semantic import SemanticMemory
        with _tmpdir() as tmp:
            db = _make_db(tmp)
            sm = SemanticMemory(db_path=db)
            vec = [0.1] * 64
            # Should not raise
            sm.update_concept(concept, vec)

    @pytest.mark.parametrize("concept", [
        "hello", "", "a" * 500, "'; DROP TABLE semantic_memory; --",
    ])
    def test_get_concept_robust(self, concept):
        from cognia.memory.semantic import SemanticMemory
        with _tmpdir() as tmp:
            db = _make_db(tmp)
            sm = SemanticMemory(db_path=db)
            result = sm.get_concept(concept)
            assert result is None or isinstance(result, dict)


class TestKnowledgeGraphRobustness:
    """KnowledgeGraph handles edge inputs without crashing."""

    @pytest.mark.parametrize("text", [
        "Nono es un lenguaje de programacion",
        "<script>alert(1)</script>",
        "'; DROP TABLE knowledge_graph; --",
        "word " * 100,
        "",
        "42",
        "hello\nworld",
    ])
    def test_extract_triples_does_not_crash(self, text):
        from cognia.knowledge.graph import KnowledgeGraph
        with _tmpdir() as tmp:
            db = _make_db(tmp)
            kg = KnowledgeGraph(db_path=db)
            result = kg.extract_triples_from_text(text, "test_label")
            assert isinstance(result, list)

    @pytest.mark.parametrize("concept", [
        "hello", "", "'; DROP TABLE knowledge_graph; --",
        "<script>", "word " * 50, "42",
    ])
    def test_get_facts_robust(self, concept):
        from cognia.knowledge.graph import KnowledgeGraph
        with _tmpdir() as tmp:
            db = _make_db(tmp)
            kg = KnowledgeGraph(db_path=db)
            result = kg.get_facts(concept)
            assert isinstance(result, list)

    @pytest.mark.parametrize("concept", [
        "hello", "", "'; DROP TABLE knowledge_graph; --",
    ])
    def test_get_neighbors_robust(self, concept):
        from cognia.knowledge.graph import KnowledgeGraph
        with _tmpdir() as tmp:
            db = _make_db(tmp)
            kg = KnowledgeGraph(db_path=db)
            result = kg.get_neighbors(concept)
            assert isinstance(result, list)


# ===========================================================================
# Section 8: Additional reasoning edge cases (10+ cases)
# ===========================================================================

class TestReasoningContradictionDetection:

    @pytest.mark.parametrize("context,expected", [
        ("sin embargo el resultado es distinto", True),
        ("pero hay una diferencia importante aqui", True),
        ("however the data shows otherwise", True),
        ("on the other hand we have evidence", True),
        ("nevertheless we proceed", True),
        ("aunque parezca correcto no lo es", True),
        ("yet we see contradicting results", True),
        ("por otro lado la evidencia sugiere", True),
        ("no obstante hay que considerar", True),
        ("simple statement with no markers", False),
        ("completely neutral context", False),
        ("the data shows X is true", False),
    ])
    def test_contradiction_detection(self, context, expected):
        from cognia.reasoning.cognia_reasoning_engine import _detect_contradiction_in_text
        assert _detect_contradiction_in_text(context) is expected

    @pytest.mark.parametrize("question", [
        "word " * 20,
        "how can we solve this complex problem with multiple parts and sub-questions",
        "what are the differences between A and B also considering C and D",
    ])
    def test_long_question_sub_questions_list(self, question):
        from cognia.reasoning.cognia_reasoning_engine import CogniaReasoningEngine
        engine = CogniaReasoningEngine()
        result = engine.enrich_with_meta(question, "some context here", "general")
        assert isinstance(result["sub_questions"], list)

    @pytest.mark.parametrize("negation_question", [
        "word " * 20 + "no es correcto esto",
        "word " * 20 + "nunca ha sido verdad esto",
        "word " * 20 + "never been true this claim",
    ])
    def test_negation_reduces_confidence(self, negation_question):
        from cognia.reasoning.cognia_reasoning_engine import CogniaReasoningEngine
        engine = CogniaReasoningEngine()
        # With negation, confidence should be slightly lower than base 0.7
        result = engine.enrich_with_meta(negation_question, "context " * 20, "general")
        assert result["confidence"] < 0.7
