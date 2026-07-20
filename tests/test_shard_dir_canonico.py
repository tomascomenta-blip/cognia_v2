"""
El directorio de shards se resuelve en UN solo sitio.

Bug del 2026-07-20: el doctor y el orquestador resolvian SHARD_WEIGHTS_DIR por
separado y discrepaban. Con la variable sin setear, el orquestador hacia
Path("") y la resolvia contra la raiz del repo — un directorio que existe — asi
que is_dir() pasaba, buscaba shard_0.npz alli, no lo encontraba y devolvia
False EN SILENCIO. En una instalacion por defecto (shards en ~/.cognia/shards/)
la inferencia por shards no arrancaba nunca, y el doctor decia "4 shards OK"
dos lineas antes de "shards no detectados".
"""

import os
from pathlib import Path

import pytest

from shattering.model_constants import shard_weights_dir


@pytest.fixture
def sin_env(monkeypatch):
    monkeypatch.delenv("SHARD_WEIGHTS_DIR", raising=False)
    monkeypatch.delenv("COGNIA_SWARM_MODEL", raising=False)


def _crear_shards(dir_: Path) -> Path:
    dir_.mkdir(parents=True, exist_ok=True)
    for i in range(4):
        (dir_ / f"shard_{i}.npz").write_bytes(b"x")
    return dir_


def test_sin_variable_no_devuelve_la_raiz_del_repo(sin_env, monkeypatch, tmp_path):
    """El bug exacto: sin la variable, no puede resolver a un dir cualquiera."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "vacio"))
    resuelto = shard_weights_dir()
    raiz_repo = str(Path(__file__).resolve().parent.parent)
    assert resuelto != raiz_repo, "resolvio a la raiz del repo: el bug original"


def test_encuentra_la_instalacion_por_defecto(sin_env, monkeypatch, tmp_path):
    """Los shards que instala `python -m cognia` viven en ~/.cognia/shards/."""
    home = tmp_path / "home"
    _crear_shards(home / ".cognia" / "shards" / "qwen-coder-3b-q4")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    assert Path(shard_weights_dir()) == home / ".cognia" / "shards" / "qwen-coder-3b-q4"


def test_la_variable_manda_sobre_el_default(sin_env, monkeypatch, tmp_path):
    home = tmp_path / "home"
    _crear_shards(home / ".cognia" / "shards" / "qwen-coder-3b-q4")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    explicito = _crear_shards(tmp_path / "explicito")
    monkeypatch.setenv("SHARD_WEIGHTS_DIR", str(explicito))

    assert Path(shard_weights_dir()) == explicito


def test_variable_rota_no_cae_a_otro_sitio_en_silencio(sin_env, monkeypatch, tmp_path):
    """Si te piden un dir que no existe, decilo: no busques por tu cuenta."""
    home = tmp_path / "home"
    _crear_shards(home / ".cognia" / "shards" / "qwen-coder-3b-q4")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("SHARD_WEIGHTS_DIR", str(tmp_path / "no" / "existe"))

    assert shard_weights_dir() == ""


def test_doctor_y_orquestador_ven_lo_mismo(sin_env, monkeypatch, tmp_path):
    """La contradiccion que delato el bug: '4 shards OK' vs 'no detectados'."""
    home = tmp_path / "home"
    _crear_shards(home / ".cognia" / "shards" / "qwen-coder-3b-q4")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    from cognia.doctor import _shard_dir

    del_doctor = _shard_dir()
    assert del_doctor, "el doctor no ve los shards instalados"

    # El orquestador acepta el mismo directorio: mismo criterio de presencia.
    from shattering.orchestrator import ShatteringOrchestrator

    orch = object.__new__(ShatteringOrchestrator)
    assert orch._shards_available() is True, (
        "el doctor ve los shards y el orquestador no: la discrepancia del bug"
    )
