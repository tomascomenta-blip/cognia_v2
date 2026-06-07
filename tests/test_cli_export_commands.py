"""
tests/test_cli_export_commands.py
==================================
Tests for /exportar and /exportar-stats CLI commands.
"""
import sys
import os
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure project root is on path
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))


# ---------------------------------------------------------------------------
# Helpers to import the CLI functions without triggering full Cognia init
# ---------------------------------------------------------------------------

def _import_cli_fns():
    """Return (_slash_exportar, _slash_exportar_stats) imported from cognia.cli."""
    import cognia.cli as cli_mod
    return cli_mod._slash_exportar, cli_mod._slash_exportar_stats


# ---------------------------------------------------------------------------
# Fake HistoryExporter used by most tests
# ---------------------------------------------------------------------------

def _make_fake_exporter(messages=None):
    if messages is None:
        messages = [
            {"role": "user", "content": "hola", "timestamp": "2026-06-02T10:00:00+00:00"},
            {"role": "assistant", "content": "buenas", "timestamp": "2026-06-02T10:00:01+00:00"},
        ]
    exporter = MagicMock()
    exporter.get_messages.return_value = messages
    exporter.to_json.return_value = '{"messages": []}'
    exporter.to_markdown.return_value = "# Chat"
    exporter.to_csv.return_value = "timestamp,role,content\n"
    return exporter


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSlashExportarHelp:
    def test_no_args_prints_help(self, capsys):
        _slash_exportar, _ = _import_cli_fns()
        _slash_exportar("")
        out = capsys.readouterr().out
        assert "Uso:" in out
        assert "json" in out
        assert "csv" in out

    def test_no_args_no_crash(self):
        _slash_exportar, _ = _import_cli_fns()
        _slash_exportar("")  # must not raise


class TestSlashExportarJson:
    def test_json_creates_file(self, tmp_path, capsys):
        _slash_exportar, _ = _import_cli_fns()
        out_file = tmp_path / "out.json"
        fake_exporter = _make_fake_exporter()
        with patch("cognia.export.history_exporter.HistoryExporter", return_value=fake_exporter):
            with patch("builtins.open", wraps=open):
                import cognia.cli as cli_mod
                original = getattr(cli_mod, "_slash_exportar")
                # Patch Path.write_text to write inside tmp_path instead
                orig_write_text = Path.write_text

                def _patched_write_text(self_path, content, **kw):
                    # redirect to tmp_path
                    target = tmp_path / self_path.name
                    orig_write_text(target, content, **kw)

                with patch.object(Path, "write_text", _patched_write_text):
                    original("json")

        out = capsys.readouterr().out
        # Should confirm export happened
        assert "json" in out.lower() or "historial" in out.lower() or "exportado" in out.lower()

    def test_json_with_explicit_filename(self, tmp_path, capsys):
        _slash_exportar, _ = _import_cli_fns()
        fake_exporter = _make_fake_exporter()
        orig_write_text = Path.write_text

        written = {}

        def _capture_write(self_path, content, **kw):
            written["path"] = str(self_path)
            written["content"] = content

        with patch("cognia.export.history_exporter.HistoryExporter", return_value=fake_exporter):
            with patch.object(Path, "write_text", _capture_write):
                _slash_exportar("json output.json")

        assert written.get("path", "").endswith("output.json")

    def test_md_explicit_filename(self, tmp_path, capsys):
        _slash_exportar, _ = _import_cli_fns()
        fake_exporter = _make_fake_exporter()

        written = {}

        def _capture_write(self_path, content, **kw):
            written["path"] = str(self_path)

        with patch("cognia.export.history_exporter.HistoryExporter", return_value=fake_exporter):
            with patch.object(Path, "write_text", _capture_write):
                _slash_exportar("md output.md")

        assert written.get("path", "").endswith("output.md")


class TestSlashExportarInvalidFormat:
    def test_invalid_format_prints_error(self, capsys):
        _slash_exportar, _ = _import_cli_fns()
        _slash_exportar("invalido")
        out = capsys.readouterr().out
        assert "no valido" in out.lower() or "disponibles" in out.lower() or "formato" in out.lower()

    def test_invalid_format_no_crash(self):
        _slash_exportar, _ = _import_cli_fns()
        _slash_exportar("xml")  # must not raise


class TestSlashExportarStats:
    def test_stats_prints_statistics(self, capsys):
        _, _slash_exportar_stats = _import_cli_fns()
        messages = [
            {"role": "user", "content": "hola", "timestamp": "2026-06-02T10:00:00+00:00"},
            {"role": "assistant", "content": "buenas", "timestamp": "2026-06-02T10:00:01+00:00"},
            {"role": "user", "content": "adios", "timestamp": "2026-06-02T10:00:02+00:00"},
        ]
        fake_exporter = _make_fake_exporter(messages)
        with patch("cognia.export.history_exporter.HistoryExporter", return_value=fake_exporter):
            import cognia.cli as cli_mod
            # _show_response uses _print_line which may use rich — capture plain print fallback
            with patch.object(cli_mod, "_show_response", side_effect=lambda text, *a, **kw: print(text)):
                _slash_exportar_stats()

        out = capsys.readouterr().out
        assert "Total mensajes" in out
        assert "usuario" in out.lower()
        assert "Cognia" in out or "cognia" in out.lower()
