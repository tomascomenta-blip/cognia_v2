"""
tests/test_cli_session_tools.py
================================
Tests for /ver-contexto, /resumen-sesion, /limpiar-sesion CLI commands.
"""

import time
import importlib
import sys
import types


def _get_cli():
    """Import cognia.cli with a minimal Cognia stub to avoid DB/model loading."""
    # Provide a minimal stub for cognia.cognia if not already available
    if "cognia.cognia" not in sys.modules:
        stub = types.ModuleType("cognia.cognia")
        class _FakeCognia:
            def __init__(self, *a, **kw): pass
        stub.Cognia = _FakeCognia
        sys.modules["cognia.cognia"] = stub

    if "cognia.config" not in sys.modules:
        cfg_stub = types.ModuleType("cognia.config")
        cfg_stub.HAS_RESEARCH_ENGINE = False
        cfg_stub.HAS_PROGRAM_CREATOR = False
        sys.modules["cognia.config"] = cfg_stub

    import cognia.cli as cli
    return cli


def test_ver_contexto_no_args_prints_usage(capsys):
    cli = _get_cli()
    cli._slash_ver_contexto("")
    captured = capsys.readouterr()
    assert "Uso:" in captured.out
    assert "/ver-contexto" in captured.out


def test_resumen_sesion_shows_duration(capsys, monkeypatch):
    cli = _get_cli()
    # Set _session_start to 5 minutes ago
    monkeypatch.setattr(cli, "_session_start", time.time() - 300)
    monkeypatch.setattr(cli, "_history", [])
    monkeypatch.setattr(cli, "_session_feedback", [])
    cli._slash_resumen_sesion_full("")
    captured = capsys.readouterr()
    assert "Duracion" in captured.out
    assert "5" in captured.out or "4" in captured.out  # ~5 min


def test_limpiar_sesion_clears_history(monkeypatch):
    cli = _get_cli()
    monkeypatch.setattr(cli, "_history", [
        {"role": "user", "content": "hola"},
        {"role": "assistant", "content": "hola de vuelta"},
    ])
    monkeypatch.setattr(cli, "_session_feedback", [{"signal": "positive"}])
    cli._slash_limpiar_sesion("")
    assert cli._history == []
    assert cli._session_feedback == []


def test_limpiar_sesion_shows_count(capsys, monkeypatch):
    cli = _get_cli()
    monkeypatch.setattr(cli, "_history", [
        {"role": "user", "content": "msg1"},
        {"role": "assistant", "content": "resp1"},
        {"role": "user", "content": "msg2"},
    ])
    monkeypatch.setattr(cli, "_session_feedback", [{"signal": "negative"}, {"signal": "positive"}])
    cli._slash_limpiar_sesion("")
    captured = capsys.readouterr()
    assert "3" in captured.out   # 3 history entries
    assert "2" in captured.out   # 2 feedback entries


def test_resumen_sesion_shows_command_count(capsys, monkeypatch):
    cli = _get_cli()
    monkeypatch.setattr(cli, "_session_start", time.time())
    monkeypatch.setattr(cli, "_history", [
        {"role": "user", "content": "/metas"},
        {"role": "assistant", "content": "sin metas"},
        {"role": "user", "content": "hola"},
        {"role": "assistant", "content": "hola"},
        {"role": "user", "content": "/ayuda"},
        {"role": "assistant", "content": "ayuda"},
    ])
    monkeypatch.setattr(cli, "_session_feedback", [])
    cli._slash_resumen_sesion_full("")
    captured = capsys.readouterr()
    assert "Comandos usados" in captured.out
    # 2 slash commands (/metas and /ayuda)
    assert "2" in captured.out
