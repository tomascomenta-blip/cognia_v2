"""
tests/test_context_injector.py
==============================
Tests para cognia.context_injector.ContextInjector.
"""

import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_injector(goal_summary="", insights=None):
    """
    Construye un ContextInjector con GoalTracker y CuriosityEngine mockeados.
    """
    from cognia.context_injector import ContextInjector

    injector = ContextInjector.__new__(ContextInjector)
    injector._available = True

    gt = MagicMock()
    gt.get_active_goals_summary.return_value = goal_summary
    injector._goal_tracker = gt

    ce = MagicMock()
    ce.get_insights.return_value = insights or []
    injector._curiosity_engine = ce

    return injector


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestContextInjectorReturnType:
    """get_context_block() siempre retorna str."""

    def test_returns_string_when_available(self):
        inj = _make_injector()
        result = inj.get_context_block("local")
        assert isinstance(result, str)

    def test_returns_string_when_unavailable(self):
        from cognia.context_injector import ContextInjector
        inj = ContextInjector.__new__(ContextInjector)
        inj._available = False
        inj._goal_tracker = None
        inj._curiosity_engine = None
        result = inj.get_context_block("local")
        assert isinstance(result, str)
        assert result == ""


class TestContextInjectorGoals:
    """Cuando GoalTracker tiene metas el bloque las incluye."""

    def test_goals_present_in_block(self):
        inj = _make_injector(goal_summary="Metas activas: [Aprender Python (45%)]")
        block = inj.get_context_block("user1")
        assert "Metas activas:" in block

    def test_block_header_present_when_goals_exist(self):
        inj = _make_injector(goal_summary="Metas activas: [X (10%)]")
        block = inj.get_context_block("user1")
        assert "[Contexto del usuario]" in block

    def test_empty_when_no_goals_and_no_insights(self):
        inj = _make_injector(goal_summary="", insights=[])
        block = inj.get_context_block("user1")
        assert block == ""


class TestContextInjectorInsights:
    """Insights de curiosity aparecen cuando existen respuestas en BD."""

    def test_insights_present_in_block(self):
        insights = [
            {"question": "¿Qué no entiendo sobre Python?", "answer": "algo"},
            {"question": "¿Cuál es el estado del arte en ML?", "answer": "mucho"},
        ]
        inj = _make_injector(insights=insights)
        block = inj.get_context_block("local")
        assert "Conocimiento reciente:" in block

    def test_max_3_insights(self):
        insights = [
            {"question": f"Pregunta {i}?", "answer": "resp"}
            for i in range(10)
        ]
        inj = _make_injector(insights=insights)
        # get_insights es llamado con limit=3, devolvemos 10 pero el injector
        # solo usa los primeros 3 del resultado
        block = inj.get_context_block("local")
        # Contar apariciones de "Pregunta" — deben ser <= 3
        assert block.count("Pregunta") <= 3


class TestContextInjectorRobustness:
    """No lanza excepcion si las dependencias fallan."""

    def test_no_exception_when_unavailable(self):
        from cognia.context_injector import ContextInjector
        inj = ContextInjector.__new__(ContextInjector)
        inj._available = False
        inj._goal_tracker = None
        inj._curiosity_engine = None
        # No debe lanzar
        inj.get_context_block("local")

    def test_no_exception_when_goal_tracker_raises(self):
        from cognia.context_injector import ContextInjector
        inj = ContextInjector.__new__(ContextInjector)
        inj._available = True

        gt = MagicMock()
        gt.get_active_goals_summary.side_effect = RuntimeError("DB error")
        inj._goal_tracker = gt

        ce = MagicMock()
        ce.get_insights.return_value = []
        inj._curiosity_engine = ce

        result = inj.get_context_block("local")
        assert isinstance(result, str)

    def test_no_exception_when_curiosity_engine_raises(self):
        from cognia.context_injector import ContextInjector
        inj = ContextInjector.__new__(ContextInjector)
        inj._available = True

        gt = MagicMock()
        gt.get_active_goals_summary.return_value = ""
        inj._goal_tracker = gt

        ce = MagicMock()
        ce.get_insights.side_effect = RuntimeError("DB error")
        inj._curiosity_engine = ce

        result = inj.get_context_block("local")
        assert isinstance(result, str)


class TestContextInjectorLengthLimit:
    """El bloque no excede 500 caracteres."""

    def test_block_max_500_chars(self):
        long_summary = "Metas activas: [" + ", ".join(
            [f"Meta muy larga numero {i} con descripcion extensa ({i}%)" for i in range(20)]
        ) + "]"
        insights = [
            {"question": "¿Pregunta larga sobre un tema muy especifico y detallado?", "answer": "x"}
            for _ in range(3)
        ]
        inj = _make_injector(goal_summary=long_summary, insights=insights)
        block = inj.get_context_block("local")
        assert len(block) <= 500


class TestContextInjectorSingleton:
    """El singleton de modulo es importable y es ContextInjector."""

    def test_singleton_importable(self):
        from cognia.context_injector import _context_injector, ContextInjector
        assert isinstance(_context_injector, ContextInjector)

    def test_singleton_get_context_block_callable(self):
        from cognia.context_injector import _context_injector
        result = _context_injector.get_context_block("local")
        assert isinstance(result, str)
