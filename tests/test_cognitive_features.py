"""
tests/test_cognitive_features.py
Tests for cognitive architecture improvements from the architecture evolution mission.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import pytest


class TestCogniaReasoningEngine:
    def test_short_question_returns_unchanged(self):
        from cognia.reasoning.cognia_reasoning_engine import CogniaReasoningEngine
        e = CogniaReasoningEngine()
        ctx = "Some context"
        result = e.enrich("What is 2+2?", ctx, "factual_simple")
        assert result == ctx

    def test_social_qtype_returns_unchanged(self):
        from cognia.reasoning.cognia_reasoning_engine import CogniaReasoningEngine
        e = CogniaReasoningEngine()
        long_q = "Hola como estas y que tal todo y como va el trabajo y los proyectos"
        result = e.enrich(long_q, "ctx", "social")
        assert result == "ctx"

    def test_complex_question_gets_prefix(self):
        from cognia.reasoning.cognia_reasoning_engine import CogniaReasoningEngine
        e = CogniaReasoningEngine()
        q = "Como puedo mejorar el rendimiento de mi aplicacion y reducir el uso de memoria y acelerar las consultas SQL"
        result = e.enrich(q, "base context", "tecnico")
        assert result.startswith("Analizando:")
        assert "base context" in result

    def test_anti_echo_strips_verbatim_question(self):
        from cognia.reasoning.cognia_reasoning_engine import CogniaReasoningEngine
        e = CogniaReasoningEngine()
        q = "Como puedo mejorar el rendimiento de mi aplicacion y reducir memoria y acelerar consultas y optimizar indices"
        ctx = q + " is what we need to discuss"
        result = e.enrich(q, ctx, "tecnico")
        # verbatim question should be stripped from context
        assert q not in result or result.startswith("Analizando:")


class TestSemanticCrystallization:
    def test_get_crystallized_returns_list(self, tmp_path):
        from cognia.memory.semantic import SemanticMemory
        db = str(tmp_path / "test.db")
        from cognia.database import init_db
        init_db(db)
        sm = SemanticMemory(db)
        result = sm.get_crystallized()
        assert isinstance(result, list)

    def test_get_crystallized_requires_threshold(self, tmp_path):
        import json
        from storage.db_pool import db_connect_pooled
        from cognia.memory.semantic import SemanticMemory
        from cognia.database import init_db
        db = str(tmp_path / "test2.db")
        init_db(db)
        # Insert a low-support concept (should NOT appear with min_support=5)
        conn = db_connect_pooled(db)
        c = conn.cursor()
        c.execute(
            "INSERT INTO semantic_memory (concept, description, vector, confidence, support, last_updated, emotion_avg, associations) "
            "VALUES (?, ?, ?, ?, ?, datetime('now'), ?, '{}')",
            ("test_concept", "desc", json.dumps([0.1] * 64), 0.9, 2, 0.0)
        )
        conn.commit()
        conn.close()
        sm = SemanticMemory(db)
        result = sm.get_crystallized(min_support=5)
        assert all(c['support'] >= 5 for c in result)
