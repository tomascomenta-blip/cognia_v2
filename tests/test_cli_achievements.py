"""
tests/test_cli_achievements.py
Tests for /logros and /patrones CLI commands (Cycle 26B).
"""
import sys
import os
import unittest
from unittest.mock import patch, MagicMock

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _import_funcs():
    import importlib
    import cognia.cli as cli_mod
    return cli_mod


class TestLogrosConnectionError(unittest.TestCase):
    """_slash_logros handles connection error gracefully."""

    def test_connection_error_prints_unavailable(self):
        cli = _import_funcs()
        import requests as req_mod
        with patch.object(req_mod, "get", side_effect=Exception("connection refused")):
            import io
            from contextlib import redirect_stdout
            buf = io.StringIO()
            with redirect_stdout(buf):
                cli._slash_logros("")
            output = buf.getvalue()
        self.assertIn("no disponible", output)


class TestPatronesEmptyHistory(unittest.TestCase):
    """_slash_patrones with empty _history prints no-history message."""

    def test_empty_history(self):
        cli = _import_funcs()
        import io
        from contextlib import redirect_stdout
        original = list(cli._history)
        cli._history.clear()
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                cli._slash_patrones("")
            output = buf.getvalue()
        finally:
            cli._history.extend(original)
        self.assertIn("No hay historial", output)


class TestPatronesCountsQuestionWords(unittest.TestCase):
    """_slash_patrones detects dominant question word."""

    def test_counts_como(self):
        cli = _import_funcs()
        import io
        from contextlib import redirect_stdout
        original = list(cli._history)
        cli._history.clear()
        cli._history.extend([
            {"role": "user", "content": "como funciona esto"},
            {"role": "assistant", "content": "respuesta"},
            {"role": "user", "content": "como se llama"},
            {"role": "user", "content": "como puedo hacerlo"},
        ])
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                cli._slash_patrones("")
            output = buf.getvalue()
        finally:
            cli._history.clear()
            cli._history.extend(original)
        self.assertIn("como", output)
        self.assertIn("3", output)


class TestLogrosTodosParam(unittest.TestCase):
    """_slash_logros todos passes show_all=True and shows locked achievements."""

    def test_todos_shows_locked_items(self):
        cli = _import_funcs()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {"name": "Principiante", "points": 10, "description": "Primer mensaje", "unlocked": False},
            {"name": "Experto", "points": 50, "description": "100 mensajes", "unlocked": True},
        ]
        mock_stats = MagicMock()
        mock_stats.status_code = 200
        mock_stats.json.return_value = {"unlocked": 1, "total": 2, "points": 50}

        import requests as req_mod
        import io
        from contextlib import redirect_stdout
        with patch.object(req_mod, "get", side_effect=[mock_resp, mock_stats]):
            buf = io.StringIO()
            with redirect_stdout(buf):
                cli._slash_logros("todos")
            output = buf.getvalue()
        self.assertIn("[ ]", output)
        self.assertIn("[X]", output)
        self.assertIn("Principiante", output)


class TestPatronesFindsTopKeywords(unittest.TestCase):
    """_slash_patrones identifies top keywords from user messages."""

    def test_top_keywords(self):
        cli = _import_funcs()
        import io
        from contextlib import redirect_stdout
        original = list(cli._history)
        cli._history.clear()
        cli._history.extend([
            {"role": "user", "content": "python programacion avanzada"},
            {"role": "user", "content": "python es genial para programacion"},
            {"role": "user", "content": "quiero aprender python programacion"},
        ])
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                cli._slash_patrones("")
            output = buf.getvalue()
        finally:
            cli._history.clear()
            cli._history.extend(original)
        self.assertIn("python", output)
        self.assertIn("Patrones", output)


if __name__ == "__main__":
    unittest.main()
