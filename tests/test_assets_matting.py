# -*- coding: utf-8 -*-
"""Tests del recorte universal con BiRefNet (partes CPU/sin-GPU).

La segmentación real (BiRefNet en GPU) se verifica end-to-end en venv312gpu,
fuera de la suite. Aquí se prueba el plumbing determinista: kill-switch, chequeo
de disponibilidad y la combinación de alfa (puro PIL, sin torch). El módulo
importa en CPU porque torch/transformers/torchvision son imports perezosos."""
import importlib

import pytest

mt = importlib.import_module("cognia.assets.matting")


def test_import_no_arrastra_torch():
    # Importar el paquete de assets NO debe requerir torch (imports perezosos).
    mod = importlib.import_module("cognia.assets")
    assert hasattr(mod, "quitar_fondo")
    assert hasattr(mod, "birefnet_disponible")


def test_birefnet_killswitch(monkeypatch):
    monkeypatch.setenv("COGNIA_ASSETS", "0")
    ok, motivo = mt.birefnet_disponible()
    assert ok is False
    assert "COGNIA_ASSETS=0" in motivo


def test_birefnet_disponible_devuelve_tupla(monkeypatch):
    monkeypatch.delenv("COGNIA_ASSETS", raising=False)
    r = mt.birefnet_disponible()
    assert isinstance(r, tuple) and len(r) == 2 and isinstance(r[0], bool)


def test_combinar_alfa_respeta_transparencia_previa():
    from PIL import Image
    # máscara BiRefNet: todo foreground (255). alfa previo: mitad ya transparente.
    mask = Image.new("L", (64, 64), 255)
    alfa = Image.new("L", (64, 64), 0)
    for y in range(32):          # mitad superior opaca en el original
        for x in range(64):
            alfa.putpixel((x, y), 255)
    out = mt._combinar_alfa(mask, alfa)
    # donde el original era transparente (mitad inferior) sigue 0 aunque BiRefNet
    # marcara foreground; donde había opacidad conserva la máscara (255).
    assert out.getpixel((10, 10)) == 255    # arriba: se mantiene la máscara
    assert out.getpixel((10, 50)) == 0      # abajo: no se resucita


def test_combinar_alfa_recorta_por_mascara():
    from PIL import Image
    # original totalmente opaco; BiRefNet marca solo un cuadro central.
    mask = Image.new("L", (64, 64), 0)
    for y in range(20, 44):
        for x in range(20, 44):
            mask.putpixel((x, y), 255)
    alfa = Image.new("L", (64, 64), 255)
    out = mt._combinar_alfa(mask, alfa)
    assert out.getpixel((32, 32)) == 255    # centro: foreground
    assert out.getpixel((2, 2)) == 0        # esquina: fondo recortado
