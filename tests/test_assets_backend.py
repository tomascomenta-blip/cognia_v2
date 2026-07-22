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
    mod = importlib.import_module("cognia.assets")
    assert hasattr(mod, "generar_transparente")
    assert hasattr(mod, "estilos_disponibles")


def test_componer_prompt_con_trigger():
    p = cb._componer_prompt("a chest", asset=True, trigger="pvz, cartoon")
    assert p.startswith("pvz, cartoon, a chest")
    assert "isolated single object" in p


def test_registro_estilos():
    assert "pixel" in cb._ESTILOS and "pvz" in cb._ESTILOS
    assert cb._ESTILOS["pixel"]["downscale"] == 8
    assert cb._ESTILOS["pvz"]["trigger"] == "pvz, cartoon"


def test_estilos_disponibles_es_lista():
    r = cb.estilos_disponibles()
    assert isinstance(r, list)
    assert set(r).issubset(set(cb._ESTILOS))


def test_estilo_desconocido_no_esta_en_registro():
    assert "inexistente_xyz" not in cb._ESTILOS


def test_pixelar_preserva_tamano_y_alfa():
    from PIL import Image
    im = Image.new("RGBA", (256, 256), (200, 50, 50, 255))
    out = cb._pixelar(im, 8)
    assert out.size == (256, 256) and out.mode == "RGBA"
    # factor 1 o 0 -> no cambia
    assert cb._pixelar(im, 1) is im


def test_recortar_alfa_bbox():
    from PIL import Image
    # lienzo 256x256 transparente con un cuadro opaco 40x40 en (100,100)
    im = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    for y in range(100, 140):
        for x in range(100, 140):
            im.putpixel((x, y), (255, 0, 0, 255))
    out = cb._recortar_alfa(im, margen=0)
    assert out.size == (40, 40)
    # con margen 8 crece 16 en cada dimension (8 por lado, sin salir del lienzo)
    out2 = cb._recortar_alfa(im, margen=8)
    assert out2.size == (56, 56)


def test_recortar_alfa_todo_transparente_no_rompe():
    from PIL import Image
    im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    assert cb._recortar_alfa(im) is im  # bbox None -> devuelve la misma


def test_frac_transparente():
    pytest.importorskip("numpy")
    from PIL import Image
    # 64x64, mitad transparente (alfa 0) mitad opaca (alfa 255)
    im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    for y in range(32):
        for x in range(64):
            im.putpixel((x, y), (10, 20, 30, 255))
    f = cb.frac_transparente(im)
    assert 0.45 < f < 0.55  # ~50%
    # todo transparente -> ~1.0
    assert cb.frac_transparente(Image.new("RGBA", (32, 32), (0, 0, 0, 0))) > 0.99
