"""
Tests for CLI personalization: persistent theme + accent color.

Pins set_config_value (preserves comments, updates in place) and the /tema /color
handlers (validate input, update state, persist) -- isolated from the real
~/.cognia/config.env.
"""

import pytest

from cognia import first_run
from cognia import cli


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    home = tmp_path / ".cognia"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(first_run, "COGNIA_HOME", home)
    monkeypatch.setattr(first_run, "CONFIG_FILE", home / "config.env")
    return home / "config.env"


def test_set_config_value_creates_and_reads(cfg):
    first_run.set_config_value("COGNIA_THEME", "claro")
    assert "COGNIA_THEME=claro" in cfg.read_text(encoding="utf-8")
    assert first_run._load_config()["COGNIA_THEME"] == "claro"


def test_set_config_value_updates_in_place_preserving_others(cfg):
    cfg.write_text("# mi comentario\nOLLAMA_URL=http://x\nCOGNIA_THEME=oscuro\n",
                   encoding="utf-8")
    first_run.set_config_value("COGNIA_THEME", "alto_contraste")
    text = cfg.read_text(encoding="utf-8")
    assert "# mi comentario" in text          # comment preserved
    assert "OLLAMA_URL=http://x" in text        # other key preserved
    assert "COGNIA_THEME=alto_contraste" in text
    assert text.count("COGNIA_THEME=") == 1     # updated in place, not duplicated


def test_slash_color_accepts_valid_and_persists(monkeypatch):
    saved = {}
    monkeypatch.setattr(cli, "_persist_setting", lambda k, v: saved.update({k: v}))
    old = cli._ACCENT
    try:
        cli._slash_color("magenta")
        assert cli._ACCENT == "magenta"
        assert saved.get("COGNIA_ACCENT") == "magenta"
    finally:
        cli._ACCENT = old


def test_slash_color_rejects_invalid(monkeypatch):
    monkeypatch.setattr(cli, "_persist_setting", lambda k, v: None)
    old = cli._ACCENT
    try:
        cli._slash_color("no-es-un-color-valido-xyz")
        assert cli._ACCENT == old  # unchanged
    finally:
        cli._ACCENT = old


def test_slash_tema_sets_named_theme(monkeypatch):
    saved = {}
    monkeypatch.setattr(cli, "_persist_setting", lambda k, v: saved.update({k: v}))
    old = cli._theme_idx
    try:
        cli._slash_tema("claro")
        assert cli._THEME_ORDER[cli._theme_idx] == "claro"
        assert saved.get("COGNIA_THEME") == "claro"
    finally:
        cli._theme_idx = old


def test_slash_tema_rejects_unknown(monkeypatch):
    monkeypatch.setattr(cli, "_persist_setting", lambda k, v: None)
    old = cli._theme_idx
    try:
        cli._slash_tema("inexistente")
        assert cli._theme_idx == old  # unchanged
    finally:
        cli._theme_idx = old
