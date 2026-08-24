# -*- coding: utf-8 -*-
"""
tests/test_cli_banner_layout.py
===============================
Regresion del banner de arranque a 100 columnas (juicio visual 2026-08-24).

QUE PROTEGE: a 100 columnas (media pantalla, el ancho mas comun) el grid de
_print_banner_completo repartia por RATIO 3:2 y la columna del arte quedaba
en ~56 para un logo COGNIA de 63: cada fila del logo envolvia y la 'A' caia
sola a la linea siguiente (10 lineas para un logo de 5). A 80 y a 120 entraba.
La regla nueva vive en harness/banner_adaptativo.cabe_dos_columnas: dos
columnas SOLO si arte ENTERO + guia ENTERA caben; si no, apilado.

Snapshot REAL: se pinta con la Console de rich del CLI (tema real) a un ancho
fijo y se comprueba que las 5 filas del logo salen ENTERAS y que ninguna
linea supera el ancho. Sin mocks del layout.
"""
from __future__ import annotations

import io
import re

import pytest

rich_console = pytest.importorskip("rich.console")

import cognia.cli as cli  # noqa: E402
from cognia.harness.banner_adaptativo import ancho_visible  # noqa: E402


def _filas_logo() -> list:
    """Las 5 filas del logo COGNIA en bloques, tal cual viven en _BANNER_RAW."""
    filas = [l.rstrip() for l in cli._BANNER_RAW.split("\n")
             if "█" in l or "╗" in l]
    assert len(filas) == 5, filas
    return filas


def _pintar(ancho: int, monkeypatch, variante: str = "completo",
            alto: int = 60) -> str:
    monkeypatch.setenv("COGNIA_BANNER", variante)
    buf = io.StringIO()
    # legacy_windows=False: con la deteccion automatica rich resta 1 columna
    # sobre un StringIO en Windows y el snapshot no seria el de una terminal
    # moderna (Windows Terminal), que es donde el juez lo vio.
    con = rich_console.Console(
        file=buf, width=ancho, height=alto,
        theme=cli._THEMES[cli._THEME_ORDER[cli._theme_idx]],
        highlight=False, force_terminal=False, legacy_windows=False)
    monkeypatch.setattr(cli, "_console", con)
    cli._print_banner_completo()
    return buf.getvalue()


@pytest.mark.parametrize("ancho", [80, 100, 104, 112, 120, 160])
def test_el_logo_sale_entero_y_nada_desborda(ancho, monkeypatch):
    salida = _pintar(ancho, monkeypatch)
    lineas = salida.splitlines()
    for fila in _filas_logo():
        # Cada fila del logo tiene que estar ENTERA en una sola linea pintada
        # (a 100 columnas la 'A' final caia sola a la linea de abajo).
        assert any(fila.strip() in l for l in lineas), (
            f"a {ancho} columnas la fila del logo se parte: {fila.strip()!r}")
    con_bloques = [l for l in lineas if "█" in l or "╗" in l]
    assert len(con_bloques) == 5, (
        f"a {ancho} columnas el logo ocupa {len(con_bloques)} lineas, no 5")
    for l in lineas:
        assert ancho_visible(l) <= ancho, (ancho, ancho_visible(l), l)


def test_a_100_columnas_se_apila_y_a_120_va_a_dos_columnas(monkeypatch):
    """La guia 'Para empezar' se pone AL LADO del arte solo cuando cabe."""
    s100 = _pintar(100, monkeypatch).splitlines()
    s120 = _pintar(120, monkeypatch).splitlines()
    braille = re.compile("[⠀-⣿]")
    # A 120: hay lineas con arte Braille Y texto de la guia a la vez.
    assert any(braille.search(l) and "/hacer" in l for l in s120)
    # A 100: ninguna linea mezcla arte y guia (apilado), y la guia esta.
    assert not any(braille.search(l) and "/hacer" in l for l in s100)
    assert any("/hacer" in l for l in s100)
    # Y en ninguno de los dos anchos la linea de atajos se parte.
    for lineas in (s100, s120):
        assert any("Tab" in l and "/ayuda" in l and "todo" in l for l in lineas)


@pytest.mark.parametrize("ancho", [80, 100, 120])
def test_la_variante_medio_recorta_el_gato_y_conserva_el_logo(ancho, monkeypatch):
    """A 40 filas (variante 'medio') el recorte por altura se comia el logo
    COGNIA: el bloque entero (gato + logo) se recortaba simetricamente. El
    logo es identidad y sale ENTERO; lo que cede altura es el gato."""
    lineas = _pintar(ancho, monkeypatch, variante="medio", alto=40).splitlines()
    con_bloques = [l for l in lineas if "█" in l or "╗" in l]
    assert len(con_bloques) == 5, (ancho, len(con_bloques))
    for fila in _filas_logo():
        assert any(fila.strip() in l for l in lineas), (ancho, fila.strip())
    # Y sigue cabiendo: el banner medio nunca pinta mas que la terminal
    # menos el aire del prompt.
    assert len(lineas) <= 40 - 3, (ancho, len(lineas))
