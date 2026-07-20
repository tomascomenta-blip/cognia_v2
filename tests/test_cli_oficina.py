"""
tests/test_cli_oficina.py
==========================
Tests for the /oficina CLI command: lanza (o reutiliza) el dashboard de la
oficina isometrica (`python -m cognia.oficina`) como proceso detached y abre
el navegador. El comando NUNCA debe cargar el modelo ni bloquear el REPL --
por eso el check de "esta viva" vive en su propia funcion (_oficina_responde)
que estos tests mockean en vez de pegarle a la red real.
"""
import subprocess
import sys
import types
import webbrowser
from unittest.mock import MagicMock


def _get_cli():
    """Import cognia.cli with a minimal Cognia stub to avoid DB/model loading."""
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


# ---------------------------------------------------------------------------
# (a) el comando existe y aparece en el help
# ---------------------------------------------------------------------------

def test_oficina_registered_in_command_descriptions():
    cli = _get_cli()
    assert "/oficina" in cli._CMD_DESCRIPTIONS


def test_oficina_appears_in_help_text():
    cli = _get_cli()
    assert "/oficina" in cli.HELP_TEXT


def test_oficina_function_exists_and_is_callable():
    cli = _get_cli()
    assert callable(cli._slash_oficina)


# ---------------------------------------------------------------------------
# (b) puerto libre -> lanza Popen detached, espera al poll y abre navegador
# ---------------------------------------------------------------------------

def test_oficina_launches_when_port_free(monkeypatch):
    cli = _get_cli()

    # 1ra llamada (chequeo inicial, antes de lanzar) = puerto libre; desde la
    # 2da llamada (poll tras el Popen) = ya responde, simulando que el
    # servidor arranco durante la espera.
    calls = {"n": 0}
    def _fake_responde(url):
        calls["n"] += 1
        return calls["n"] > 1

    mock_popen = MagicMock()
    mock_open = MagicMock()
    monkeypatch.setattr(cli, "_oficina_responde", _fake_responde)
    monkeypatch.setattr(subprocess, "Popen", mock_popen)
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)  # no esperar de verdad
    monkeypatch.setattr(webbrowser, "open", mock_open)

    cli._slash_oficina("")

    mock_popen.assert_called_once()
    popen_args = mock_popen.call_args[0][0]
    assert popen_args[0] == sys.executable
    assert popen_args[1:4] == ["-m", "cognia.oficina", "--puerto"]
    assert popen_args[4] == "8766"   # 8766 desde 2026-07-15 (8765 es del desktop API)
    # detached: stdout/stderr silenciados
    assert mock_popen.call_args.kwargs.get("stdout") is subprocess.DEVNULL
    assert mock_popen.call_args.kwargs.get("stderr") is subprocess.DEVNULL

    mock_open.assert_called_once_with("http://127.0.0.1:8766/")


def test_oficina_custom_port_used_in_popen_and_url(monkeypatch):
    cli = _get_cli()
    calls = {"n": 0}
    def _fake_responde(url):
        calls["n"] += 1
        return calls["n"] > 1

    mock_popen = MagicMock()
    mock_open = MagicMock()
    monkeypatch.setattr(cli, "_oficina_responde", _fake_responde)
    monkeypatch.setattr(subprocess, "Popen", mock_popen)
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)
    monkeypatch.setattr(webbrowser, "open", mock_open)

    cli._slash_oficina("9100")

    popen_args = mock_popen.call_args[0][0]
    assert popen_args[-1] == "9100"
    mock_open.assert_called_once_with("http://127.0.0.1:9100/")


# ---------------------------------------------------------------------------
# (c) puerto ya ocupado por una oficina viva -> NO relanza, solo abre navegador
# ---------------------------------------------------------------------------

def test_oficina_reuses_when_already_running(monkeypatch):
    cli = _get_cli()

    mock_popen = MagicMock()
    mock_open = MagicMock()
    monkeypatch.setattr(cli, "_oficina_responde", lambda url: True)
    monkeypatch.setattr(subprocess, "Popen", mock_popen)
    monkeypatch.setattr(webbrowser, "open", mock_open)

    cli._slash_oficina("9999")

    mock_popen.assert_not_called()
    mock_open.assert_called_once_with("http://127.0.0.1:9999/")


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_oficina_invalid_port_shows_usage_and_does_not_launch(monkeypatch, capsys):
    cli = _get_cli()
    mock_popen = MagicMock()
    monkeypatch.setattr(subprocess, "Popen", mock_popen)

    cli._slash_oficina("no-es-un-puerto")

    mock_popen.assert_not_called()
    out = capsys.readouterr().out
    assert "Uso" in out and "/oficina" in out


def test_oficina_timeout_reports_clean_error_no_traceback(monkeypatch, capsys):
    cli = _get_cli()
    # nunca responde ni antes ni durante el poll -> agota el timeout
    monkeypatch.setattr(cli, "_oficina_responde", lambda url: False)
    monkeypatch.setattr(subprocess, "Popen", MagicMock())
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)
    monkeypatch.setattr(webbrowser, "open", MagicMock())

    cli._slash_oficina("8765")

    out = capsys.readouterr().out
    assert "Traceback" not in out
    assert "8765" in out
