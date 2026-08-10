# -*- coding: utf-8 -*-
"""Regresion VISUAL del CLI via el arnes de escenas (scripts/escenas_cli.py).

POR QUE: las escenas alimentan al Renderer REAL con eventos sinteticos fijos;
si un cambio de estetica rompe una linea (marca, sangria, footer), el
export_text lo caza como diff determinista SIN modelo ni GPU.

NOTA sobre determinismo: el SVG binario NO es reproducible entre corridas
(el spinner de rich hornea 1-2 frames segun timing del hilo de refresco),
asi que el gate compara export_text — el TEXTO si es identico corrida a
corrida. Nunca usar diff de bytes del SVG como assert.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _cargar_modulo():
    """Carga scripts/escenas_cli.py por ruta (scripts/ no es paquete)."""
    ruta = REPO / "scripts" / "escenas_cli.py"
    spec = importlib.util.spec_from_file_location("escenas_cli", ruta)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ESC = _cargar_modulo()


def _correr_escena(nombre: str, tema: str = "oscuro"):
    """Corre una escena del renderer sobre una console grabadora fresca
    (una console por escena: el buffer record es acumulativo)."""
    from cognia.ux.renderer import Renderer
    con = ESC.consola_grabadora(tema)
    r = Renderer(con)
    ESC.ESCENAS[nombre](r)
    r._parar_status()
    return con


# ---------------------------------------------------------------------------
# Exportacion: cada escena produce un SVG no vacio
# ---------------------------------------------------------------------------

def test_exportar_todas_las_escenas_svg_no_vacio(tmp_path):
    rutas = ESC.exportar(tmp_path, temas=("oscuro",))
    nombres = {p.name for p in rutas}
    esperadas = {"banner_oscuro.svg", "chat_oscuro.svg", "agente_oscuro.svg",
                 "pensando_oscuro.svg", "degradado_oscuro.svg",
                 "archivos_oscuro.svg", "pensar_visible_oscuro.svg",
                 "selector_oscuro.svg"}
    assert esperadas <= nombres, f"faltan escenas: {esperadas - nombres}"
    for p in rutas:
        assert p.exists(), f"no existe {p}"
        assert p.stat().st_size > 500, f"SVG sospechosamente vacio: {p.name}"


def test_tema_claro_tambien_exporta(tmp_path):
    rutas = ESC.exportar(tmp_path, temas=("claro",), escena="archivos")
    assert len(rutas) == 1
    svg = tmp_path / "archivos_claro.svg"
    assert svg.exists() and svg.stat().st_size > 500


def test_resolver_temas():
    assert ESC._resolver_temas("oscuro") == ("oscuro",)
    assert ESC._resolver_temas("oscuro,claro") == ("oscuro", "claro")
    assert "claro" in ESC._resolver_temas("todos")
    with pytest.raises(SystemExit):
        ESC._resolver_temas("fucsia")


# ---------------------------------------------------------------------------
# Escena archivos: el path de lo escrito se VE en la salida
# ---------------------------------------------------------------------------

def test_escena_archivos_contiene_el_path():
    con = _correr_escena("archivos")
    texto = con.export_text()
    assert ESC.ARCHIVO_DEMO in texto
    # la escena cubre el ciclo completo: escribir, editar, apendar, leer
    assert "Escribiendo" in texto
    assert "Editando" in texto
    assert "Leyendo" in texto


# ---------------------------------------------------------------------------
# pensar_visible: los fragmentos solo salen con COGNIA_PENSAR=ver
# ---------------------------------------------------------------------------

def test_pensar_visible_muestra_fragmentos_solo_con_flag(monkeypatch):
    monkeypatch.delenv("COGNIA_PENSAR", raising=False)
    from cognia.ux.renderer import Renderer

    # CON flag: la escena lo setea por dentro (y lo restaura)
    con_flag = _correr_escena("pensar_visible")
    texto_con = con_flag.export_text()

    # SIN flag: mismos ticks, sin setear el env
    con_sin = ESC.consola_grabadora("oscuro")
    r = Renderer(con_sin)
    ESC._ticks_pensar(r)
    r._parar_status()
    texto_sin = con_sin.export_text()

    # marca corta: el fragmento entero se envuelve al ancho de la console
    # (100 cols) y un `in` sobre el texto completo fallaria por el \n
    marca = ESC.FRAGMENTOS_PENSAR[0].strip()[:30]
    assert marca in texto_con, "con COGNIA_PENSAR=ver el fragmento debe verse"
    assert marca not in texto_sin, "sin el flag el razonamiento NO se muestra"
    # la respuesta final sale en ambos casos
    assert "n(n+1)/2" in texto_con and "n(n+1)/2" in texto_sin


def test_pensar_visible_restaura_el_env():
    # la escena setea COGNIA_PENSAR=ver POR DENTRO y debe dejarlo como estaba
    previo = os.environ.get("COGNIA_PENSAR")
    _correr_escena("pensar_visible")
    assert os.environ.get("COGNIA_PENSAR") == previo


# ---------------------------------------------------------------------------
# Determinismo del TEXTO (el SVG binario NO: spinner, documentado arriba)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("nombre", ["archivos", "agente", "degradado"])
def test_export_text_determinista_en_dos_corridas(nombre):
    t1 = _correr_escena(nombre).export_text()
    t2 = _correr_escena(nombre).export_text()
    assert t1 == t2, f"escena {nombre}: el texto exportado no es determinista"


# ---------------------------------------------------------------------------
# Selector: frame estatico con las opciones visibles
# ---------------------------------------------------------------------------

def test_selector_frame_estatico():
    con = ESC.consola_grabadora("oscuro")
    ESC._escena_selector(con)
    texto = con.export_text()
    # las opciones se ven tanto con render_frame real (E2) como con el mock
    assert "qwythos-9b" in texto
    assert "gpt-oss-20b" in texto


# ---------------------------------------------------------------------------
# El arnes no contamina el proceso (env restaurado tras exportar)
# ---------------------------------------------------------------------------

def test_exportar_restaura_env_remoto(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIA_REMOTO", "1")
    ESC.exportar(tmp_path, temas=("oscuro",), escena="degradado")
    assert os.environ.get("COGNIA_REMOTO") == "1"
