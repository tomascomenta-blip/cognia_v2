"""
tests/test_cli_config.py
Tests for the persistent user config system added in Cycle 21B.
"""
import json
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def tmp_config(tmp_path, monkeypatch):
    """Redirect config path to a temp file for each test."""
    import cognia.cli as cli_mod
    fake_path = tmp_path / ".cognia_config.json"
    monkeypatch.setattr(cli_mod, "_CONFIG_PATH", fake_path)
    yield fake_path


def test_load_defaults_when_no_file():
    from cognia.cli import _load_config, _CONFIG_DEFAULTS
    cfg = _load_config()
    assert cfg == _CONFIG_DEFAULTS


def test_set_key_persists(tmp_path, monkeypatch):
    import cognia.cli as cli_mod
    fake_path = tmp_path / ".cognia_config.json"
    monkeypatch.setattr(cli_mod, "_CONFIG_PATH", fake_path)

    cli_mod._save_config({**cli_mod._CONFIG_DEFAULTS, "idioma": "es"})
    loaded = cli_mod._load_config()
    assert loaded["idioma"] == "es"


def test_reset_writes_defaults(tmp_path, monkeypatch, capsys):
    import cognia.cli as cli_mod
    fake_path = tmp_path / ".cognia_config.json"
    monkeypatch.setattr(cli_mod, "_CONFIG_PATH", fake_path)

    cli_mod._save_config({**cli_mod._CONFIG_DEFAULTS, "persona": "formal"})
    cli_mod._slash_config("reset")
    loaded = cli_mod._load_config()
    assert loaded["persona"] == cli_mod._CONFIG_DEFAULTS["persona"]
    out = capsys.readouterr().out
    assert "restablecida" in out.lower()


def test_exportar_is_valid_json(tmp_path, monkeypatch, capsys):
    import cognia.cli as cli_mod
    fake_path = tmp_path / ".cognia_config.json"
    monkeypatch.setattr(cli_mod, "_CONFIG_PATH", fake_path)

    cli_mod._slash_config("exportar")
    out = capsys.readouterr().out
    parsed = json.loads(out.strip())
    assert "persona" in parsed


def test_unknown_key_rejected(tmp_path, monkeypatch, capsys):
    import cognia.cli as cli_mod
    fake_path = tmp_path / ".cognia_config.json"
    monkeypatch.setattr(cli_mod, "_CONFIG_PATH", fake_path)

    cli_mod._slash_config("set clave_invalida valor")
    out = capsys.readouterr().out
    assert "desconocida" in out.lower() or "invalida" in out.lower() or "valida" in out.lower()


def test_unknown_subcommand_prints_usage(tmp_path, monkeypatch, capsys):
    import cognia.cli as cli_mod
    fake_path = tmp_path / ".cognia_config.json"
    monkeypatch.setattr(cli_mod, "_CONFIG_PATH", fake_path)

    cli_mod._slash_config("opcion_no_existe")
    out = capsys.readouterr().out
    assert "/config" in out


def test_config_persists_across_load_calls(tmp_path, monkeypatch):
    import cognia.cli as cli_mod
    fake_path = tmp_path / ".cognia_config.json"
    monkeypatch.setattr(cli_mod, "_CONFIG_PATH", fake_path)

    cfg1 = cli_mod._load_config()
    cfg1["nivel_detalle"] = "verbose"
    cli_mod._save_config(cfg1)

    cfg2 = cli_mod._load_config()
    assert cfg2["nivel_detalle"] == "verbose"
