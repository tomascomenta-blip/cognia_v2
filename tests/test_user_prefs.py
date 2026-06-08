"""
tests/test_user_prefs.py
========================
Personalization preferences (cognia/user_prefs.py): the explicit, user-set
name/language/style that the onboarding wizard and `cognia modo` persist and
that get folded into the system prompt at chat time.

Key invariant: with nothing configured, personalize_prompt is a NO-OP, so a
fresh user's canonical identity prompt is never altered.
"""

from __future__ import annotations

import os

from cognia import user_prefs as up
from shattering.model_constants import COGNIA_SYSTEM_PROMPT


def test_suffix_empty_is_blank():
    assert up.personalization_suffix({}) == ""
    assert up.personalization_suffix({up.K_USER_NAME: "", up.K_LANG: "", up.K_STYLE: ""}) == ""


def test_suffix_includes_name_lang_style():
    s = up.personalization_suffix({
        up.K_USER_NAME: "Tomas", up.K_LANG: "espanol", up.K_STYLE: "breve",
    })
    assert "Tomas" in s
    assert "espanol" in s.lower()
    assert "breves" in s.lower()
    # ASCII-safe for the CP1252 CLI
    s.encode("ascii")


def test_suffix_partial_only_name():
    s = up.personalization_suffix({up.K_USER_NAME: "Ana"})
    assert "Ana" in s
    assert "idioma" not in s.lower()  # no language line when unset


def test_personalize_prompt_noop_when_empty():
    # The canonical identity prompt must survive untouched for a fresh user.
    assert up.personalize_prompt(COGNIA_SYSTEM_PROMPT, {}) == COGNIA_SYSTEM_PROMPT


def test_personalize_prompt_appends():
    out = up.personalize_prompt("BASE", {up.K_USER_NAME: "Leo"})
    assert out.startswith("BASE")
    assert "Leo" in out


def test_save_load_roundtrip(tmp_path, monkeypatch):
    from cognia import first_run
    cfg = tmp_path / "config.env"
    monkeypatch.setattr(first_run, "COGNIA_HOME", tmp_path)
    monkeypatch.setattr(first_run, "CONFIG_FILE", cfg)
    touched = []
    try:
        up.save_pref(up.K_USER_NAME, "Tomas"); touched.append(up.K_USER_NAME)
        up.save_pref(up.K_RUN_MODE, "local");  touched.append(up.K_RUN_MODE)
        up.save_pref(up.K_STYLE, "tecnica");   touched.append(up.K_STYLE)
        prefs = up.load_prefs()
        assert prefs[up.K_USER_NAME] == "Tomas"
        assert prefs[up.K_RUN_MODE] == "local"
        assert prefs[up.K_STYLE] == "tecnica"
    finally:
        # set_config_value also writes os.environ; keep the suite clean.
        for k in touched:
            os.environ.pop(k, None)


def test_cli_exposes_modo_command():
    import inspect
    from cognia import __main__ as m
    assert hasattr(m, "_cmd_modo")
    src = inspect.getsource(m.main)
    assert '"modo"' in src or "'modo'" in src
