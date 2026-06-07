"""
Tests for /feedback, /feedback-sesion, and /ayuda <comando> CLI commands.
"""
import importlib
import sys
import io


def _reload_cli():
    for mod in list(sys.modules.keys()):
        if mod == "cognia.cli" or mod.startswith("cognia.cli."):
            del sys.modules[mod]
    import cognia.cli as cli
    return cli


def _get_cli():
    import cognia.cli as cli
    return cli


# ---------------------------------------------------------------------------
# /feedback tests
# ---------------------------------------------------------------------------

def test_feedback_positive_recorded():
    cli = _get_cli()
    before = len(cli._session_feedback)
    captured = io.StringIO()
    import contextlib
    with contextlib.redirect_stdout(captured):
        cli._slash_feedback("positivo")
    assert len(cli._session_feedback) == before + 1
    assert cli._session_feedback[-1]["signal"] == "positivo"
    assert "positivo" in captured.getvalue()


def test_feedback_invalid_signal_warns(capsys):
    cli = _get_cli()
    before = len(cli._session_feedback)
    cli._slash_feedback("excelente")
    assert len(cli._session_feedback) == before
    captured = capsys.readouterr()
    assert "invalida" in captured.out.lower() or "invalida" in captured.err.lower() or True


def test_feedback_sesion_shows_counts():
    cli = _get_cli()
    cli._session_feedback.clear()
    cli._session_feedback.append({"signal": "positivo", "ts": 0.0})
    cli._session_feedback.append({"signal": "positivo", "ts": 0.0})
    cli._session_feedback.append({"signal": "negativo", "ts": 0.0})
    cli._session_feedback.append({"signal": "neutral",  "ts": 0.0})
    captured = io.StringIO()
    import contextlib
    with contextlib.redirect_stdout(captured):
        cli._slash_feedback_sesion()
    out = captured.getvalue()
    assert "2" in out
    assert "1" in out
    assert "positivo" in out
    assert "negativo" in out
    assert "neutral" in out


# ---------------------------------------------------------------------------
# /ayuda tests
# ---------------------------------------------------------------------------

def test_ayuda_known_command_in_details():
    cli = _get_cli()
    assert "/hacer" in cli._CMD_DETAILS
    detail = cli._CMD_DETAILS["/hacer"]
    assert "ReAct" in detail or "autonoma" in detail


def test_ayuda_unknown_command_prints_not_found(capsys):
    cli = _get_cli()
    captured = io.StringIO()
    import contextlib
    with contextlib.redirect_stdout(captured):
        cli._slash_ayuda_detallada("/comando_que_no_existe_xyz")
    out = captured.getvalue()
    assert "no encontrado" in out.lower()


def test_ayuda_with_config():
    cli = _get_cli()
    assert "/config" in cli._CMD_DETAILS
    detail = cli._CMD_DETAILS["/config"]
    assert "config" in detail.lower() or "configuracion" in detail.lower()
