"""
tests/test_cli_kg_commands.py
==============================
Tests for KG CLI commands: /kg-agregar, /kg-stats, /kg-predicados, /kg-exportar
"""

import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers to import the CLI functions without booting the full Cognia stack
# ---------------------------------------------------------------------------

def _import_cli_fns():
    """Import the four KG slash-command functions from cognia.cli."""
    import importlib
    cli = importlib.import_module("cognia.cli")
    return (
        cli._slash_kg_agregar,
        cli._slash_kg_stats,
        cli._slash_kg_predicados,
        cli._slash_kg_exportar,
    )


# ---------------------------------------------------------------------------
# /kg-agregar
# ---------------------------------------------------------------------------

class TestKgAgregar:
    def test_agregar_calls_add_triple(self, capsys):
        """_slash_kg_agregar calls add_triple with correct subject/predicate/object."""
        mock_kg = MagicMock()
        mock_kg_cls = MagicMock(return_value=mock_kg)

        with (
            patch("cognia.cli._slash_kg_agregar.__module__"),  # no-op, just context
            patch.dict("sys.modules", {}),
        ):
            fn, *_ = _import_cli_fns()
            with (
                patch("cognia.knowledge.graph.KnowledgeGraph", mock_kg_cls),
                patch("cognia.cli._print_line"),
            ):
                # Re-import inside patch context so module-level import resolution works
                from cognia import cli as _cli
                with (
                    patch.object(_cli, "_slash_kg_agregar", wraps=_cli._slash_kg_agregar),
                ):
                    with patch("cognia.knowledge.graph.KnowledgeGraph", mock_kg_cls):
                        _cli._slash_kg_agregar("Python es_un lenguaje")

        mock_kg.add_triple.assert_called_once_with("Python", "es_un", "lenguaje", weight=0.8)
        captured = capsys.readouterr()
        assert "Python" in captured.out

    def test_agregar_empty_args_prints_help(self, capsys):
        """_slash_kg_agregar with empty string prints help without crash."""
        from cognia import cli as _cli
        with patch.object(_cli, "_print_line") as mock_pl:
            _cli._slash_kg_agregar("")
        assert mock_pl.called
        # Should not have called print() for success
        captured = capsys.readouterr()
        assert "Triple agregado" not in captured.out

    def test_agregar_single_token_prints_help(self, capsys):
        """_slash_kg_agregar with only 1 token prints help without crash."""
        from cognia import cli as _cli
        with patch.object(_cli, "_print_line") as mock_pl:
            _cli._slash_kg_agregar("solo_uno")
        assert mock_pl.called
        captured = capsys.readouterr()
        assert "Triple agregado" not in captured.out

    def test_agregar_two_tokens_prints_help(self, capsys):
        """_slash_kg_agregar with only 2 tokens prints help without crash."""
        from cognia import cli as _cli
        with patch.object(_cli, "_print_line") as mock_pl:
            _cli._slash_kg_agregar("Python es_un")
        assert mock_pl.called
        captured = capsys.readouterr()
        assert "Triple agregado" not in captured.out


# ---------------------------------------------------------------------------
# /kg-stats
# ---------------------------------------------------------------------------

class TestKgStats:
    def test_kg_stats_does_not_raise(self):
        """_slash_kg_stats with a mock DB connection does not raise."""
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (42,)
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        from cognia import cli as _cli
        with (
            patch("storage.db_pool.db_connect_pooled", return_value=mock_conn),
            patch.object(_cli, "_show_response") as mock_sr,
        ):
            _cli._slash_kg_stats("")

        assert mock_sr.called

    def test_kg_stats_shows_totals(self):
        """_slash_kg_stats formats output with expected labels."""
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (7,)
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        from cognia import cli as _cli
        captured_args = []

        def capture_sr(text, color):
            captured_args.append(text)

        with (
            patch("storage.db_pool.db_connect_pooled", return_value=mock_conn),
            patch.object(_cli, "_show_response", side_effect=capture_sr),
        ):
            _cli._slash_kg_stats("")

        assert captured_args, "Expected _show_response to be called"
        output = captured_args[0]
        assert "Triples totales" in output
        assert "Conceptos unicos" in output
        assert "Predicados unicos" in output


# ---------------------------------------------------------------------------
# /kg-predicados
# ---------------------------------------------------------------------------

class TestKgPredicados:
    def test_kg_predicados_does_not_raise(self):
        """_slash_kg_predicados with a mock DB connection does not raise."""
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [("is_a",), ("related_to",)]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        from cognia import cli as _cli
        with (
            patch("storage.db_pool.db_connect_pooled", return_value=mock_conn),
            patch.object(_cli, "_show_response") as mock_sr,
        ):
            _cli._slash_kg_predicados("")

        assert mock_sr.called

    def test_kg_predicados_empty_prints_detail(self):
        """_slash_kg_predicados with no rows prints a detail line."""
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = []
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        from cognia import cli as _cli
        with (
            patch("storage.db_pool.db_connect_pooled", return_value=mock_conn),
            patch.object(_cli, "_print_line") as mock_pl,
        ):
            _cli._slash_kg_predicados("")

        assert mock_pl.called


# ---------------------------------------------------------------------------
# /kg-exportar
# ---------------------------------------------------------------------------

class TestKgExportar:
    def test_kg_exportar_creates_valid_json(self, tmp_path, capsys):
        """_slash_kg_exportar writes valid JSON with expected keys."""
        out_file = tmp_path / "test_kg.json"

        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [
            ("python", "is_a", "lenguaje", 0.8),
            ("cognia", "related_to", "ia", 1.0),
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        from cognia import cli as _cli
        with patch("storage.db_pool.db_connect_pooled", return_value=mock_conn):
            _cli._slash_kg_exportar(str(out_file))

        assert out_file.exists(), "El archivo JSON no fue creado"
        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["subject"] == "python"
        assert data[0]["predicate"] == "is_a"
        assert data[0]["object"] == "lenguaje"
        assert "weight" in data[0]

        captured = capsys.readouterr()
        assert "KG exportado" in captured.out
        assert "2 triples" in captured.out

    def test_kg_exportar_default_filename(self, tmp_path, capsys, monkeypatch):
        """_slash_kg_exportar with empty args uses kg_export.json."""
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = []
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        # Change cwd to tmp_path so the default file lands there
        monkeypatch.chdir(tmp_path)

        from cognia import cli as _cli
        with patch("storage.db_pool.db_connect_pooled", return_value=mock_conn):
            _cli._slash_kg_exportar("")

        assert (tmp_path / "kg_export.json").exists()
