# -*- coding: utf-8 -*-
"""Regresion: una descarga de shard FALLIDA no puede reportarse como exito.

Bug (deuda tecnica cazada 2026-07-16): ShardDownloader.download() con
_try_hf_download fallido devolvia DownloadResult(ok=True, mode="simulation")
y escribia shard_meta.json. Consecuencias reales:
  1. El caller creia que habia pesos y el nodo servia capas SIMULADAS como
     si fueran inferencia real (viola "nada de mocks/stubs" en produccion).
  2. is_downloaded() quedaba True para siempre: el nodo jamas reintentaba
     la descarga real en arranques posteriores.
Ademas, el catalogo apuntaba los sub-modelos logos/techne/rhetor a repos
HF cognia-ai/* que no existen (404 garantizado -> simulacion universal).
"""
import os

import pytest

from node.downloader import MODEL_CATALOG, DownloadResult, ShardDownloader


@pytest.fixture
def dl(tmp_path, monkeypatch):
    monkeypatch.setattr("node.downloader.SHARDS_DIR", str(tmp_path))
    return ShardDownloader(0, "qwen-coder-3b-q4")


def test_descarga_fallida_reporta_ok_false(dl, monkeypatch):
    monkeypatch.setattr(
        dl, "_try_hf_download",
        lambda on_progress: DownloadResult(ok=False, error="HTTP 404"))
    result = dl.download(on_progress=lambda pct, msg: None)
    assert result.ok is False
    assert "404" in result.error
    assert result.mode == "simulation"  # el caller sabe que NO hay pesos


def test_descarga_fallida_no_cachea_meta(dl, monkeypatch):
    """Sin shard_meta.json el proximo arranque reintenta la descarga real."""
    monkeypatch.setattr(
        dl, "_try_hf_download",
        lambda on_progress: DownloadResult(ok=False, error="HTTP 404"))
    dl.download(on_progress=lambda pct, msg: None)
    assert not os.path.exists(os.path.join(dl.output_dir, "shard_meta.json"))
    assert dl.is_downloaded() is False


def test_descarga_exitosa_sigue_ok(dl, monkeypatch):
    monkeypatch.setattr(
        dl, "_try_hf_download",
        lambda on_progress: DownloadResult(ok=True, shard_path=dl.output_dir,
                                           size_mb=12.5, mode="extracted"))
    result = dl.download(on_progress=lambda pct, msg: None)
    assert result.ok is True
    assert result.mode == "extracted"


def test_catalogo_sin_repos_fantasma():
    """Los sub-modelos shattering no pueden apuntar a repos HF inexistentes."""
    for key, source in MODEL_CATALOG.items():
        assert not source.hf_repo.startswith("cognia-ai/"), (
            f"{key} apunta a {source.hf_repo}: la org cognia-ai no existe en "
            f"HF; toda descarga daria 404 y el nodo caeria a simulacion")
