# -*- coding: utf-8 -*-
"""Instalador del stack GGUF (cognia install-model): fleet, plataforma, wiring."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from cognia import model_install as mi

REPO = Path(__file__).resolve().parents[1]


def _file_url(p: Path) -> str:
    return p.resolve().as_uri()


def test_install_fleet_descarga_manifest_y_adapters(tmp_path, monkeypatch):
    src = tmp_path / "release"
    src.mkdir()
    (src / "cognia3b_v2_f16.gguf").write_bytes(b"GGUFfake")
    (src / "adapters.json").write_text(json.dumps(
        {"adapters": [{"name": "accion", "file": "cognia3b_v2_f16.gguf"}]}),
        encoding="utf-8")
    monkeypatch.setenv("COGNIA_FLEET_URL", _file_url(src))
    dest = tmp_path / "models"
    assert mi.install_fleet(dest) == 1
    assert (dest / "adapters.json").is_file()
    assert (dest / "cognia3b_v2_f16.gguf").read_bytes() == b"GGUFfake"


def test_install_fleet_entrada_con_path_traversal_se_saltea(tmp_path, monkeypatch):
    src = tmp_path / "release"
    src.mkdir()
    (src / "adapters.json").write_text(json.dumps(
        {"adapters": [{"name": "malo", "file": "../fuera.gguf"}]}),
        encoding="utf-8")
    monkeypatch.setenv("COGNIA_FLEET_URL", _file_url(src))
    dest = tmp_path / "models"
    assert mi.install_fleet(dest) == 0
    # sin adapters validos el manifiesto se borra (evita warnings al arrancar)
    assert not (dest / "adapters.json").exists()


def test_install_fleet_sin_release_devuelve_0(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIA_FLEET_URL", _file_url(tmp_path / "no_existe"))
    assert mi.install_fleet(tmp_path / "models") == 0


def test_llama_server_plataforma_no_soportada(tmp_path, monkeypatch):
    monkeypatch.setattr(mi.platform, "system", lambda: "Linux")
    monkeypatch.setattr(mi.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(mi.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="cognia-ai"):
        mi.install_llama_server(tmp_path / "bin")


def test_llama_server_usa_binario_del_sistema_en_linux(tmp_path, monkeypatch):
    fake = tmp_path / "llama-server"
    fake.write_bytes(b"x")
    monkeypatch.setattr(mi.platform, "system", lambda: "Linux")
    monkeypatch.setattr(mi.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(mi.shutil, "which", lambda _: str(fake))
    assert mi.install_llama_server(tmp_path / "bin") == fake


def test_cli_help_incluye_install_model():
    r = subprocess.run([sys.executable, "-m", "cognia", "help"],
                       capture_output=True, text=True, cwd=str(REPO), timeout=120)
    assert "install-model" in r.stdout
