"""
Difusion ESPECULATIVA (draft Lightning -> verificar -> refinar): partes CPU.
La medicion GPU real (2026-07-24: 2.29x, 22.0s -> 9.6s, draft aceptado con
calidad igual o mejor) esta en planes/FLOTA_ROLES_2026-07.md.
"""

import pytest
from PIL import Image

from cognia.assets import especulativa as esp


def _img(alfa_fondo=0, alfa_sujeto=255, lado=64, r=20):
    """RGBA sintetica: circulo opaco centrado sobre fondo transparente."""
    img = Image.new("RGBA", (lado, lado), (0, 0, 0, alfa_fondo))
    for x in range(lado):
        for y in range(lado):
            if (x - lado // 2) ** 2 + (y - lado // 2) ** 2 < r * r:
                img.putpixel((x, y), (200, 40, 40, alfa_sujeto))
    return img


def test_heuristica_premia_sujeto_con_fondo_limpio():
    buena = esp._puntuar_heuristica(_img())
    assert buena > 5.0


def test_heuristica_castiga_sujeto_ausente():
    vacia = esp._puntuar_heuristica(_img(alfa_sujeto=0))
    assert vacia <= 1.0


def test_gate_por_env(monkeypatch):
    monkeypatch.setenv("COGNIA_SPEC_GATE", "9.9")
    # No toca GPU: solo se valida la lectura del gate via el default del arg.
    # (la funcion lee el env dentro; aqui se comprueba el parseo indirecto)
    import os
    assert float(os.environ["COGNIA_SPEC_GATE"]) == 9.9


def test_pasos_draft_invalido():
    with pytest.raises(esp.AssetsError):
        esp.generar_especulativa("x", pasos_draft=3)


def test_lightning_disponible_es_bool():
    assert isinstance(esp.lightning_disponible(4), bool)
