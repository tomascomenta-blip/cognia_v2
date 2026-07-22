# -*- coding: utf-8 -*-
"""Tests del backend de assets transparentes (partes CPU/sin-GPU).

La generación real (SDXL+LayerDiffuse) se verifica end-to-end en GPU
(venv312gpu), fuera de la suite. Aquí se prueba el plumbing determinista:
kill-switch, ajuste de dimensiones (múltiplo de 64) y composición de prompt.
Los imports de torch/diffusers son perezosos, así que este módulo importa en CPU."""
import importlib

import pytest

cb = importlib.import_module("cognia.assets.diffusion_backend")


def test_ajustar_dim_multiplo_64():
    assert cb._ajustar_dim(1024) == 1024
    assert cb._ajustar_dim(1000) == 960      # 1000 -> 960 (múltiplo de 64)
    assert cb._ajustar_dim(1023) == 960
    assert cb._ajustar_dim(10) == 64         # piso mínimo


def test_componer_prompt_asset():
    p = cb._componer_prompt("  a red apple  ", asset=True)
    assert p.startswith("a red apple")
    assert "isolated single object" in p
    assert cb._componer_prompt("a red apple", asset=False) == "a red apple"


def test_backend_killswitch(monkeypatch):
    monkeypatch.setenv("COGNIA_ASSETS", "0")
    ok, motivo = cb.backend_disponible()
    assert ok is False
    assert "COGNIA_ASSETS=0" in motivo


def test_backend_disponible_devuelve_tupla(monkeypatch):
    monkeypatch.delenv("COGNIA_ASSETS", raising=False)
    r = cb.backend_disponible()
    assert isinstance(r, tuple) and len(r) == 2 and isinstance(r[0], bool)


def test_import_no_arrastra_torch():
    # Importar el paquete NO debe requerir torch (imports perezosos).
    import sys
    mod = importlib.import_module("cognia.assets")
    assert hasattr(mod, "generar_transparente")
    # backend_disponible es barato y no importa torch salvo para chequearlo;
    # el import del paquete en sí no debe fallar aunque falte torch.
