"""
tests/test_history_exporter.py
================================
Unit tests for HistoryExporter — mocks db_pool so no real DB is needed.
"""

import csv as _csv
import importlib
import importlib.util
import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Bootstrap: insert a minimal storage.db_pool stub BEFORE the module loads,
# so neither the stub nor cognia/__init__.py triggers a real DB connection.
# We also need db_connect_pooled because cognia/cognia.py imports it.
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent

def _ensure_storage_stub():
    """Install a storage / storage.db_pool stub if not already present."""
    if "storage" not in sys.modules:
        sys.modules["storage"] = types.ModuleType("storage")

    if "storage.db_pool" in sys.modules:
        return  # already installed

    stub = types.ModuleType("storage.db_pool")

    class _FakeCtx:
        def __init__(self, rows=None):
            self._rows = rows or []

        def __enter__(self):
            conn = MagicMock()
            conn.execute.return_value.fetchall.return_value = self._rows
            conn.execute.return_value.fetchone.return_value = None
            return conn

        def __exit__(self, *_):
            pass

    class _FakePool:
        def get(self):
            return _FakeCtx()

    stub.get_pool = lambda db_path=None: _FakePool()

    # db_connect_pooled is imported by cognia/cognia.py
    def _db_connect_pooled(db_path=None):
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = []
        conn.execute.return_value.fetchone.return_value = None
        return conn

    stub.db_connect_pooled = _db_connect_pooled

    sys.modules["storage.db_pool"] = stub


_ensure_storage_stub()


# ---------------------------------------------------------------------------
# Load the exporter module directly (bypasses cognia/__init__.py import chain)
# ---------------------------------------------------------------------------

def _load_exporter():
    spec = importlib.util.spec_from_file_location(
        "cognia.export.history_exporter",
        _REPO_ROOT / "cognia" / "export" / "history_exporter.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["cognia.export.history_exporter"] = mod
    spec.loader.exec_module(mod)
    return mod


_exporter_mod = _load_exporter()
HistoryExporter = _exporter_mod.HistoryExporter


def _exporter():
    return HistoryExporter(db_path=":memory:")


# ---------------------------------------------------------------------------
# to_json tests
# ---------------------------------------------------------------------------

class TestToJson:
    def test_empty_returns_valid_json(self):
        result = _exporter().to_json([])
        data = json.loads(result)
        assert data["messages"] == []
        assert data["total_messages"] == 0
        assert "exported_at" in data

    def test_message_included(self):
        msgs = [{"role": "user", "content": "hola", "timestamp": "2026-01-01T00:00:00+00:00"}]
        result = _exporter().to_json(msgs)
        data = json.loads(result)
        assert data["total_messages"] == 1
        assert data["messages"][0]["content"] == "hola"
        assert data["messages"][0]["role"] == "user"

    def test_compact_mode(self):
        result = _exporter().to_json([], pretty=False)
        assert "\n" not in result
        json.loads(result)


# ---------------------------------------------------------------------------
# to_markdown tests
# ---------------------------------------------------------------------------

class TestToMarkdown:
    def test_empty_has_header(self):
        result = _exporter().to_markdown([])
        assert "# Cognia Chat History" in result

    def test_user_role_label(self):
        msgs = [{"role": "user", "content": "test", "timestamp": "2026-01-01T00:00:00+00:00"}]
        result = _exporter().to_markdown(msgs)
        assert "**User**" in result
        assert "test" in result

    def test_cognia_role_label(self):
        msgs = [{"role": "assistant", "content": "resp", "timestamp": "2026-01-01T00:00:00+00:00"}]
        result = _exporter().to_markdown(msgs)
        assert "**Cognia**" in result

    def test_total_count_in_output(self):
        msgs = [
            {"role": "user", "content": "a", "timestamp": "2026-01-01"},
            {"role": "assistant", "content": "b", "timestamp": "2026-01-01"},
        ]
        result = _exporter().to_markdown(msgs)
        assert "Total: 2 messages" in result


# ---------------------------------------------------------------------------
# to_csv tests
# ---------------------------------------------------------------------------

class TestToCsv:
    def test_has_header_row(self):
        result = _exporter().to_csv([])
        first_line = result.splitlines()[0]
        assert "timestamp" in first_line
        assert "role" in first_line
        assert "content" in first_line

    def test_comma_in_content_escaped(self):
        msgs = [{"role": "user", "content": "hola,mundo", "timestamp": "2026-01-01"}]
        result = _exporter().to_csv(msgs)
        lines = result.splitlines()
        assert len(lines) == 2
        data_row = lines[1]
        assert '"hola,mundo"' in data_row

    def test_multiple_messages(self):
        msgs = [
            {"role": "user", "content": "hi", "timestamp": "2026-01-01"},
            {"role": "assistant", "content": "hello", "timestamp": "2026-01-02"},
        ]
        result = _exporter().to_csv(msgs)
        lines = result.splitlines()
        assert len(lines) == 3


# ---------------------------------------------------------------------------
# get_messages tests (with patched db_pool)
# ---------------------------------------------------------------------------

class TestGetMessages:
    # Helpers shared by the simple tests so they don't rely on stub ordering.
    class _FakeCtx:
        def __enter__(self):
            conn = MagicMock()
            conn.execute.return_value.fetchall.return_value = []
            return conn
        def __exit__(self, *_):
            pass

    class _FakePool:
        def get(self):
            return TestGetMessages._FakeCtx()

    def test_returns_list(self):
        with patch.object(sys.modules["storage.db_pool"], "get_pool", return_value=self._FakePool()):
            exporter = _exporter()
            result = exporter.get_messages()
        assert isinstance(result, list)

    def test_since_filter_parsed(self):
        with patch.object(sys.modules["storage.db_pool"], "get_pool", return_value=self._FakePool()):
            exporter = _exporter()
            result = exporter.get_messages(since="2026-01-01T00:00:00")
        assert isinstance(result, list)

    def test_rows_mapped_to_dicts(self):
        """DB rows are mapped to dicts with role/content/timestamp keys."""

        class _FakeCtx:
            def __enter__(self):
                conn = MagicMock()
                conn.execute.return_value.fetchall.return_value = [
                    ("user", "hello world", 1735689600)
                ]
                return conn

            def __exit__(self, *_):
                pass

        class _FakePool:
            def get(self):
                return _FakeCtx()

        with patch.object(sys.modules["storage.db_pool"], "get_pool", return_value=_FakePool()):
            exporter = _exporter()
            msgs = exporter.get_messages()

        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "hello world"
        assert "timestamp" in msgs[0]
