"""
tests/test_cli_history_commands.py
Tests for CLI chat history commands: /sesiones, /buscar-historial,
/sesion-ver, /historial-limpiar.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import pytest
from unittest.mock import MagicMock, patch, call


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cursor(rows=None):
    """Return a mock cursor that yields rows from fetchall()."""
    cur = MagicMock()
    cur.fetchall.return_value = rows or []
    return cur


def _make_conn(cursor):
    """Return a mock connection wrapping a cursor."""
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn


# ---------------------------------------------------------------------------
# /sesiones
# ---------------------------------------------------------------------------

class TestSlashSesiones:

    def test_no_crash_on_empty(self):
        """_slash_sesiones('') should not raise when no rows returned."""
        from cognia.cli import _slash_sesiones
        cur = _make_cursor(rows=[])
        conn = _make_conn(cur)
        with patch("storage.db_pool.db_connect_pooled", return_value=conn):
            # Must not raise
            _slash_sesiones("")

    def test_no_crash_with_rows(self):
        """_slash_sesiones should not raise with valid rows."""
        from cognia.cli import _slash_sesiones
        # session_id, count, first_ts (unix int)
        rows = [
            ("abc12345-abcd-efgh", 5, 1700000000),
            ("xyz98765-abcd-efgh", 2, 1699900000),
        ]
        cur = _make_cursor(rows=rows)
        conn = _make_conn(cur)
        with patch("storage.db_pool.db_connect_pooled", return_value=conn):
            _slash_sesiones("")

    def test_query_is_parametrized(self):
        """Verify the SQL uses GROUP BY session_id."""
        from cognia.cli import _slash_sesiones
        cur = _make_cursor(rows=[])
        conn = _make_conn(cur)
        with patch("storage.db_pool.db_connect_pooled", return_value=conn):
            _slash_sesiones("")
        sql_call = cur.execute.call_args[0][0]
        assert "session_id" in sql_call.lower()
        assert "group by" in sql_call.lower()


# ---------------------------------------------------------------------------
# /buscar-historial
# ---------------------------------------------------------------------------

class TestSlashBuscarHistorial:

    def test_no_crash_with_keyword(self):
        """_slash_buscar_historial('python') should not raise."""
        from cognia.cli import _slash_buscar_historial
        rows = [
            ("ses-abc12345", "user", "Tengo una pregunta sobre python", 1700000000),
            ("ses-xyz98765", "assistant", "Python es un lenguaje interpretado", 1700000100),
        ]
        cur = _make_cursor(rows=rows)
        conn = _make_conn(cur)
        with patch("storage.db_pool.db_connect_pooled", return_value=conn):
            _slash_buscar_historial("python")

    def test_empty_keyword_prints_warning_no_db_call(self, capsys):
        """_slash_buscar_historial('') must print warning without querying DB."""
        from cognia.cli import _slash_buscar_historial
        with patch("storage.db_pool.db_connect_pooled") as mock_db:
            _slash_buscar_historial("")
        # DB should NOT be touched when no keyword provided
        mock_db.assert_not_called()

    def test_uses_like_parameter(self):
        """The SQL must use a parametrized LIKE, not an f-string."""
        from cognia.cli import _slash_buscar_historial
        cur = _make_cursor(rows=[])
        conn = _make_conn(cur)
        with patch("storage.db_pool.db_connect_pooled", return_value=conn):
            _slash_buscar_historial("test_keyword")
        sql_call, params = cur.execute.call_args[0]
        assert "LIKE" in sql_call.upper()
        # Parameter must be a tuple containing the wildcard-wrapped keyword
        assert params == ("%test_keyword%",)

    def test_no_results_does_not_crash(self):
        """No results should print a message without crashing."""
        from cognia.cli import _slash_buscar_historial
        cur = _make_cursor(rows=[])
        conn = _make_conn(cur)
        with patch("storage.db_pool.db_connect_pooled", return_value=conn):
            _slash_buscar_historial("something_unlikely")


# ---------------------------------------------------------------------------
# /sesion-ver
# ---------------------------------------------------------------------------

class TestSlashSesionVer:

    def test_empty_id_prints_warning_no_db_call(self):
        """_slash_sesion_ver('') must warn without touching DB."""
        from cognia.cli import _slash_sesion_ver
        with patch("storage.db_pool.db_connect_pooled") as mock_db:
            _slash_sesion_ver("")
        mock_db.assert_not_called()

    def test_no_crash_with_valid_id(self):
        """_slash_sesion_ver with a valid id should not raise."""
        from cognia.cli import _slash_sesion_ver
        rows = [
            ("user", "Hola Cognia", 1700000000),
            ("assistant", "Hola usuario", 1700000010),
        ]
        cur = _make_cursor(rows=rows)
        conn = _make_conn(cur)
        with patch("storage.db_pool.db_connect_pooled", return_value=conn):
            _slash_sesion_ver("abc12345")

    def test_no_rows_does_not_crash(self):
        """No matching session should print a message without crashing."""
        from cognia.cli import _slash_sesion_ver
        cur = _make_cursor(rows=[])
        conn = _make_conn(cur)
        with patch("storage.db_pool.db_connect_pooled", return_value=conn):
            _slash_sesion_ver("nonexistent-id")


# ---------------------------------------------------------------------------
# /historial-limpiar
# ---------------------------------------------------------------------------

class TestSlashHistorialLimpiar:

    def test_empty_args_prints_warning_no_delete(self):
        """_slash_historial_limpiar('') must print aviso without deleting."""
        from cognia.cli import _slash_historial_limpiar
        with patch("storage.db_pool.db_connect_pooled") as mock_db:
            _slash_historial_limpiar("")
        mock_db.assert_not_called()

    def test_confirmar_calls_delete_all(self):
        """_slash_historial_limpiar('confirmar') should execute DELETE FROM chat_history."""
        from cognia.cli import _slash_historial_limpiar
        cur = MagicMock()
        cur.rowcount = 42
        conn = MagicMock()
        conn.cursor.return_value = cur
        with patch("storage.db_pool.db_connect_pooled", return_value=conn):
            _slash_historial_limpiar("confirmar")
        sql = cur.execute.call_args[0][0]
        assert "delete from chat_history" in sql.lower()
        conn.commit.assert_called_once()

    def test_session_id_calls_delete_where(self):
        """_slash_historial_limpiar('<id>') should DELETE WHERE session_id = ?."""
        from cognia.cli import _slash_historial_limpiar
        cur = MagicMock()
        cur.rowcount = 3
        conn = MagicMock()
        conn.cursor.return_value = cur
        with patch("storage.db_pool.db_connect_pooled", return_value=conn):
            _slash_historial_limpiar("ses-abc12345")
        sql, params = cur.execute.call_args[0]
        assert "WHERE session_id" in sql.upper() or "session_id = ?" in sql.lower()
        assert params == ("ses-abc12345",)
        conn.commit.assert_called_once()
