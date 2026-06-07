"""
tests/test_cli_search_commands.py
Tests for /buscar-web and /buscar-kg CLI commands.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import pytest
from unittest.mock import MagicMock, patch


class TestSlashBuscarWeb:
    """Tests for _slash_buscar_web helper."""

    def test_no_exception_with_mock_websearch(self):
        """_slash_buscar_web with valid query and mocked WebSearch does not raise."""
        from cognia.cli import _slash_buscar_web
        mock_ws = MagicMock()
        mock_ws.search.return_value = {
            "query": "python",
            "abstract": "Python is a programming language.",
            "abstract_source": "Wikipedia",
            "related_topics": ["Python (programming)", "Django"],
            "answer": "",
            "cached": False,
            "error": None,
        }
        with patch("cognia.search.web_search.WebSearch", return_value=mock_ws):
            _slash_buscar_web("python")  # must not raise

    def test_empty_query_prints_warning_no_crash(self, capsys):
        """_slash_buscar_web with empty string prints usage warning without crashing."""
        from cognia.cli import _slash_buscar_web
        _slash_buscar_web("")
        # Must not raise; warning is printed via _print_line (may or may not hit capsys
        # depending on Rich availability, so we just assert no exception was raised)

    def test_abstract_in_output(self, capsys):
        """When WebSearch returns an abstract, output contains 'Respuesta directa:'."""
        from cognia.cli import _slash_buscar_web
        mock_ws = MagicMock()
        mock_ws.search.return_value = {
            "query": "python",
            "abstract": "Python is a high-level programming language.",
            "abstract_source": "Wikipedia",
            "related_topics": [],
            "answer": "",
            "cached": False,
            "error": None,
        }
        captured_lines = []

        def fake_show_response(text, color=None):
            captured_lines.append(text)

        with patch("cognia.search.web_search.WebSearch", return_value=mock_ws), \
             patch("cognia.cli._show_response", side_effect=fake_show_response):
            _slash_buscar_web("python")

        assert any("Respuesta directa:" in l for l in captured_lines), \
            f"Expected 'Respuesta directa:' in output, got: {captured_lines}"

    def test_answer_field_preferred_over_abstract(self):
        """When WebSearch returns an 'answer' field, it is shown as the direct answer."""
        from cognia.cli import _slash_buscar_web
        mock_ws = MagicMock()
        mock_ws.search.return_value = {
            "query": "2+2",
            "abstract": "",
            "abstract_source": "",
            "related_topics": [],
            "answer": "4",
            "cached": False,
            "error": None,
        }
        captured_lines = []

        def fake_show_response(text, color=None):
            captured_lines.append(text)

        with patch("cognia.search.web_search.WebSearch", return_value=mock_ws), \
             patch("cognia.cli._show_response", side_effect=fake_show_response):
            _slash_buscar_web("2+2")

        assert any("Respuesta directa: 4" in l for l in captured_lines), \
            f"Expected 'Respuesta directa: 4' in output, got: {captured_lines}"

    def test_websearch_import_error_prints_friendly_message(self):
        """If WebSearch cannot be imported, prints friendly error without crashing."""
        from cognia.cli import _slash_buscar_web
        with patch.dict("sys.modules", {"cognia.search.web_search": None}):
            # ImportError path — must not raise
            try:
                _slash_buscar_web("test query")
            except Exception as e:
                pytest.fail(f"Should not raise, got: {e}")

    def test_error_from_search_prints_error(self):
        """When WebSearch returns an error dict, CLI prints error without crashing."""
        from cognia.cli import _slash_buscar_web
        mock_ws = MagicMock()
        mock_ws.search.return_value = {
            "query": "test",
            "abstract": "",
            "abstract_source": "",
            "related_topics": [],
            "answer": "",
            "cached": False,
            "error": "Connection timeout",
        }
        with patch("cognia.search.web_search.WebSearch", return_value=mock_ws):
            _slash_buscar_web("test")  # must not raise


class TestSlashBuscarKG:
    """Tests for _slash_buscar_kg helper."""

    def test_no_exception_with_mock_kg(self):
        """_slash_buscar_kg with valid concept and mocked KnowledgeGraph does not raise."""
        from cognia.cli import _slash_buscar_kg
        mock_kg = MagicMock()
        mock_kg.get_facts.return_value = [
            {"subject": "python", "predicate": "is_a", "object": "language", "weight": 1.0}
        ]
        with patch("cognia.knowledge.graph.KnowledgeGraph", return_value=mock_kg), \
             patch("cognia.cli._show_response"):
            _slash_buscar_kg("python")  # must not raise

    def test_empty_concept_prints_warning_no_crash(self):
        """_slash_buscar_kg with empty string prints usage warning without crashing."""
        from cognia.cli import _slash_buscar_kg
        _slash_buscar_kg("")  # must not raise

    def test_facts_in_output(self):
        """When KG returns facts, output contains 'Hechos sobre'."""
        from cognia.cli import _slash_buscar_kg
        mock_kg = MagicMock()
        mock_kg.get_facts.return_value = [
            {"subject": "python", "predicate": "is_a", "object": "language", "weight": 1.0},
            {"subject": "python", "predicate": "has_property", "object": "dynamic", "weight": 0.8},
        ]
        captured_lines = []

        def fake_show_response(text, color=None):
            captured_lines.append(text)

        with patch("cognia.knowledge.graph.KnowledgeGraph", return_value=mock_kg), \
             patch("cognia.cli._show_response", side_effect=fake_show_response):
            _slash_buscar_kg("python")

        assert any("Hechos sobre" in l for l in captured_lines), \
            f"Expected 'Hechos sobre' in output, got: {captured_lines}"

    def test_no_facts_prints_no_hechos(self):
        """When KG returns empty list, prints 'Sin hechos en el grafo' without crashing."""
        from cognia.cli import _slash_buscar_kg
        mock_kg = MagicMock()
        mock_kg.get_facts.return_value = []
        with patch("cognia.knowledge.graph.KnowledgeGraph", return_value=mock_kg):
            _slash_buscar_kg("nonexistent_concept_xyz")  # must not raise

    def test_kg_import_error_prints_friendly_message(self):
        """If KnowledgeGraph cannot be imported, prints friendly error without crashing."""
        from cognia.cli import _slash_buscar_kg
        with patch.dict("sys.modules", {
            "cognia.knowledge.graph": None,
            "cognia.knowledge": None,
        }):
            try:
                _slash_buscar_kg("python")
            except Exception as e:
                pytest.fail(f"Should not raise, got: {e}")
