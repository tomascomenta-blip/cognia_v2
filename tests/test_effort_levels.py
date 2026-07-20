"""
tests/test_effort_levels.py
Tests de cognia/effort_levels.py (modulo puro) y del comando /esfuerzo (FASE 3).
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ── Modulo puro ────────────────────────────────────────────────────────────

def test_levels_present_and_default_valid():
    from cognia.effort_levels import EFFORT_LEVELS, DEFAULT_EFFORT, effort_names
    assert effort_names() == ["bajo", "medio", "alto", "maximo"]
    assert DEFAULT_EFFORT in EFFORT_LEVELS


def test_normalize_accepts_accents_and_synonyms():
    from cognia.effort_levels import normalize_effort
    assert normalize_effort("máximo") == "maximo"
    assert normalize_effort("MAX") == "maximo"
    assert normalize_effort("normal") == "medio"
    assert normalize_effort("  Alto ") == "alto"
    assert normalize_effort("inexistente") is None
    assert normalize_effort("") is None


def test_get_effort_falls_back_to_default():
    from cognia.effort_levels import get_effort, EFFORT_LEVELS, DEFAULT_EFFORT
    assert get_effort("alto") is EFFORT_LEVELS["alto"]
    assert get_effort("basura") is EFFORT_LEVELS[DEFAULT_EFFORT]


def test_params_are_monotonic():
    """Cada nivel gasta >= esfuerzo que el anterior en los ejes clave."""
    from cognia.effort_levels import EFFORT_LEVELS, effort_names
    keys = ["max_tokens", "alternativas", "profundidad", "verificaciones",
            "reintentos", "subtareas_max"]
    names = effort_names()
    for k in keys:
        vals = [EFFORT_LEVELS[n][k] for n in names]
        assert vals == sorted(vals), f"{k} no es monotono: {vals}"


# ── Comando /esfuerzo (CLI) ─────────────────────────────────────────────────

@pytest.fixture()
def cli_tmp_config(tmp_path, monkeypatch):
    import cognia.cli as cli_mod
    monkeypatch.setattr(cli_mod, "_CONFIG_PATH", tmp_path / ".cognia_config.json")
    return cli_mod


def test_esfuerzo_default_in_config_defaults(cli_tmp_config):
    assert cli_tmp_config._CONFIG_DEFAULTS.get("esfuerzo") == "medio"


def test_esfuerzo_shows_active_level(cli_tmp_config, capsys):
    cli_tmp_config._slash_esfuerzo("")
    out = capsys.readouterr().out.lower()
    assert "esfuerzo activo" in out and "medio" in out


def test_esfuerzo_set_persists_and_normalizes_accent(cli_tmp_config, capsys):
    cli_tmp_config._slash_esfuerzo("máximo")   # con acento -> debe normalizar a 'maximo'
    out = capsys.readouterr().out.lower()
    assert "maximo" in out
    assert cli_tmp_config._load_config()["esfuerzo"] == "maximo"


def test_esfuerzo_rejects_unknown_level(cli_tmp_config, capsys):
    cli_tmp_config._slash_esfuerzo("turbo")
    out = capsys.readouterr().out.lower()
    assert "desconocido" in out
    # config no debe cambiar ante un nivel invalido
    assert cli_tmp_config._load_config()["esfuerzo"] == "medio"


# ── FASE 3c: _active_effort() lee el nivel activo y lo usan los comandos ──────

def test_active_effort_default_medio(cli_tmp_config):
    from cognia.effort_levels import EFFORT_LEVELS
    assert cli_tmp_config._active_effort() == EFFORT_LEVELS["medio"]


def test_active_effort_reflects_set_level(cli_tmp_config):
    from cognia.effort_levels import EFFORT_LEVELS
    cli_tmp_config._slash_esfuerzo("alto")
    assert cli_tmp_config._active_effort() == EFFORT_LEVELS["alto"]
    # max_tokens del nivel activo es lo que /pensar pasa a infer()
    assert cli_tmp_config._active_effort()["max_tokens"] == EFFORT_LEVELS["alto"]["max_tokens"]


# ── FASE X: /esfuerzo tiene efecto real en el chat interactivo (fast-path) ─────

def test_chat_streaming_uses_active_effort_max_tokens_not_hardcoded():
    """El chat interactivo (dentro de repl(), rama de streaming del fast-path llama)
    debe pasar max_tokens del nivel /esfuerzo activo, no el literal 1024 de antes --
    asi /esfuerzo maximo realmente alarga la respuesta del chat. repl() es un loop
    interactivo que lee stdin: no se puede invocar de punta a punta en un test
    unitario, asi que esto es un test de regresion a nivel de fuente (falla si se
    revierte al literal hardcodeado)."""
    import inspect
    import cognia.cli as cli_mod
    src = inspect.getsource(cli_mod.repl)
    assert "max_tokens=1024" not in src
    assert '_active_effort()["max_tokens"]' in src
    # se usa en AMBAS ramas (stream_chat y stream_generate), no solo declarado
    assert src.count("_effort_max_tokens") >= 3
