# -*- coding: utf-8 -*-
"""El sistema de estilos por elemento (cognia/ux/aspecto.py) y su regla
numero uno: el DEFAULT es byte-identico al aspecto actual.

P0 (2026-08-24): SOLO el golden. Los snapshots de tests/golden/aspecto/*.ansi
se tomaron con el repo sin tocar (scripts/aspecto_snapshots.py) y este test
los regenera con las MISMAS funciones y compara los bytes. Cualquier paso
posterior (P1-P13) que cambie un byte del aspecto por defecto cae aqui, y el
mensaje dice en que byte y si cambio el texto o solo el color.

Ademas (enmienda E5 del critico): el dict literal del PTStyle del prompt,
copiado tal cual de cli._estilo_prompt, para las tres variantes. Es mas fuerte
que el ANSI de prompt_toolkit (un hex vecino cae en la misma celda) y es lo
que A.clases_pt(v) tendra que reproducir en P1.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

pytest.importorskip("rich")
pytest.importorskip("prompt_toolkit")


def _snapshots():
    """Carga scripts/aspecto_snapshots.py por ruta (scripts/ no es paquete)."""
    ruta = REPO / "scripts" / "aspecto_snapshots.py"
    spec = importlib.util.spec_from_file_location("aspecto_snapshots", ruta)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


S = _snapshots()
NOMBRES = list(S.SNAPSHOTS)


# ---------------------------------------------------------------------------
# El contrafactual: los bytes de hoy
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("nombre", NOMBRES)
def test_default_es_byte_identico_al_aspecto_actual(nombre):
    esperado = S.leer(nombre)
    obtenido = S.generar(nombre)
    assert obtenido == esperado, S.describir_diferencia(nombre, esperado, obtenido)


def test_no_hay_golden_huerfano_ni_faltante():
    """Cada snapshot del script tiene su fichero y cada fichero tiene su
    generador: un .ansi sin generador es un golden que nadie compara."""
    en_disco = {p.stem for p in S.GOLDEN.glob("*.ansi")}
    assert en_disco == set(NOMBRES), (
        f"faltan: {set(NOMBRES) - en_disco}; huerfanos: {en_disco - set(NOMBRES)}")


def test_los_snapshots_cubren_las_capacidades_que_importan():
    """Sanidad del instrumento (leccion 'el test que pasa por el motivo
    equivocado'): el golden del prompt tiene que llevar color de 24 bits
    (E5) y el del banner a 120 columnas tiene que pintar la guia (E4)."""
    assert b"38;2;" in S.leer("prompt_marco_100"), "el prompt salio sin truecolor"
    banner_120 = S.limpiar_ansi(S.leer("banner_120").decode("utf-8"))
    assert "Para empezar" in banner_120
    # a 120 la guia va AL LADO del arte: '/hacer' comparte linea con el
    # gato (Braille en blanco U+2800); a 80 va DEBAJO
    assert any("/hacer" in l and "⠀" in l for l in banner_120.splitlines()), \
        "a 120 columnas la guia deberia ir a la derecha del gato"
    banner_80 = S.limpiar_ansi(S.leer("banner_80").decode("utf-8"))
    assert "Para empezar" in banner_80
    assert b"COGNIA" in S.leer("banner_80")


# ---------------------------------------------------------------------------
# E5: el dict literal del prompt, copiado de cli._estilo_prompt (2026-08-24)
# ---------------------------------------------------------------------------

def _clases_pt_literal(variante: str) -> dict:
    """COPIA LITERAL del dict de cli._estilo_prompt. No se importa de cli a
    proposito: si alguien cambia cli, este dict ya no coincide y se ve."""
    from cognia.ux import paleta
    verde = paleta.rampa(variante)
    _MENU = paleta.MENU_PROMPT
    return {
        "":                                        f"{verde['texto']} bold",
        "marco":                                   verde["marco"],
        "cognia":                                  f"{verde['prompt']} bold",
        "flecha":                                  f"{verde['texto']} bold",
        "bottom-toolbar":                          f"noreverse bg:default {verde['marco']}",
        "bottom-toolbar.text":                     f"noreverse bg:default {verde['marco']}",
        "estado":                                  f"noreverse bg:default {verde['estado']}",
        "completion-menu.completion":              f"bg:{_MENU['fondo']} fg:{_MENU['texto']}",
        "completion-menu.completion.current":      f"bg:{_MENU['fondo_activo']} fg:{_MENU['texto_activo']}",
        "completion-menu.meta.completion":         f"bg:{_MENU['fondo']} fg:{_MENU['meta']}",
        "completion-menu.meta.completion.current": f"bg:{_MENU['fondo_activo']} fg:{_MENU['meta_activo']}",
        "scrollbar.background":                    f"bg:{_MENU['scrollbar_fondo']}",
        "scrollbar.button":                        f"bg:{_MENU['scrollbar_boton']}",
    }


LITERAL_OSCURO = {
    "": "#a6ff4d bold",
    "marco": "#4fd010",
    "cognia": "#7ee62a bold",
    "flecha": "#a6ff4d bold",
    "bottom-toolbar": "noreverse bg:default #4fd010",
    "bottom-toolbar.text": "noreverse bg:default #4fd010",
    "estado": "noreverse bg:default #8fbf5f",
    "completion-menu.completion": "bg:#1c1c2e fg:#c8c8d8",
    "completion-menu.completion.current": "bg:#004466 fg:#ffffff",
    "completion-menu.meta.completion": "bg:#1c1c2e fg:#667788",
    "completion-menu.meta.completion.current": "bg:#004466 fg:#aaccdd",
    "scrollbar.background": "bg:#1c1c2e",
    "scrollbar.button": "bg:#334455",
}


@pytest.mark.parametrize("variante", ["oscuro", "claro", "alto_contraste"])
def test_las_reglas_del_prompt_son_el_literal_actual(variante):
    import cognia.cli as C
    reglas = list(C._estilo_prompt(variante).style_rules)
    assert reglas == list(_clases_pt_literal(variante).items())


def test_el_literal_oscuro_tiene_los_hex_de_hoy():
    """Con hex escritos a mano (no derivados de la paleta): si la rampa
    cambia, esto lo dice; el golden de arriba tambien, pero este nombra el
    hex."""
    assert _clases_pt_literal("oscuro") == LITERAL_OSCURO
